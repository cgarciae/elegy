import typing as tp

import jax
import optax

from elegy import module, utils
from elegy.losses.loss import Loss
from elegy.metrics.metric import Metric
from elegy.module import Module
from elegy.module import jit as elegy_jit


class ModelBase(Module):
    def __init__(
        self,
        module: tp.Optional[Module] = None,
        loss: tp.Union[tp.Callable, tp.List, tp.Dict, None] = None,
        metrics: tp.Union[tp.Callable, tp.List, tp.Dict, None] = None,
        optimizer: tp.Optional[optax.GradientTransformation] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self.module = module
        self.loss = Losses(loss) if loss is not None else None
        self.metrics = Metrics(metrics) if metrics else None
        self.optimizer = Optimizer(optimizer) if optimizer is not None else None
        self.predict_step_jit = elegy_jit(self.predict_step)
        self.test_step_jit = elegy_jit(self.test_step)
        self.train_step_jit = elegy_jit(self.train_step)

        if self.module is not None:
            utils.wraps(self.module)(self)

    def call(self, *args, **kwargs):
        if self.module is not None:
            return self.module(*args, **kwargs)
        else:
            raise NotImplementedError("Must provide 'module' or implement 'call'.")

    def predict_step(self, x):

        x_args, x_kwargs = utils.get_input_args(x, training=module.is_training())
        y_pred = utils.inject_dependencies(self)(*x_args, **x_kwargs)

        return y_pred

    def test_step(self, x, y_true, sample_weight, class_weight):

        y_pred = self.predict_step(x)

        if self.loss is not None:
            loss_logs = self.loss(
                x=x,
                y_true=y_true,
                y_pred=y_pred,
                sample_weight=sample_weight,
                class_weight=class_weight,
                training=module.is_training(),
                parameters=self.module.get_parameters(trainable=True),
                states=self.module.get_parameters(non_trainable=True),
            )
        else:
            loss_logs = {}

        hooks_losses_logs = module.get_losses()

        if hooks_losses_logs is None:
            hooks_losses_logs = {}

        loss = sum(loss_logs.values()) + sum(hooks_losses_logs.values())

        if self.metrics is not None:
            metric_logs = self.metrics(
                x=x,
                y_true=y_true,
                y_pred=y_pred,
                sample_weight=sample_weight,
                class_weight=class_weight,
                training=module.is_training(),
                parameters=self.module.get_parameters(trainable=True),
                states=self.module.get_parameters(non_trainable=True),
            )
        else:
            metric_logs = {}

        loss_metrics_logs = {}
        loss_metrics_logs.update(hooks_losses_logs)
        loss_metrics_logs.update(loss_logs)
        loss_metrics_logs["loss"] = loss

        loss_metrics_logs = LossMetrics()(loss_metrics_logs)

        logs = {}
        logs.update(metric_logs)
        logs.update(loss_metrics_logs)

        return loss, logs

    def train_step(self, x, y_true, sample_weight, class_weight):
        assert self.optimizer is not None

        ((_, logs), grads) = module.value_and_grad(self.test_step, has_aux=True)(
            x, y_true, sample_weight, class_weight
        )

        parameters = self.module.get_parameters(trainable=True)

        parameters = self.optimizer(parameters, grads)

        if not module.is_initializing():
            self.module.set_parameters(parameters)

        return logs


class Optimizer(Module):
    def __init__(self, optimizer: optax.GradientTransformation, **kwargs):
        super().__init__(**kwargs)
        self.optax_optimizer = optimizer

    def call(self, parameters, grads):

        optimizer_state = self.add_parameter(
            "optimizer_state",
            initializer=lambda *args: self.optax_optimizer.init(parameters),
            trainable=False,
        )

        updates, optimizer_state = self.optax_optimizer.update(
            grads, optimizer_state, parameters
        )

        parameters = optax.apply_updates(parameters, updates)

        self.update_parameter("optimizer_state", optimizer_state)

        return parameters


class Losses(Module):
    def __init__(self, losses):
        super().__init__(name="losses")
        self.losses = losses

    def call(self, **kwargs):

        logs = {}

        for context, val in self.apply_recursive((), self.losses, **kwargs):
            loss_name = self.get_unique_loss_name(context, logs)
            logs[loss_name] = val

        return logs

    def apply_recursive(self, context: tp.Tuple[str, ...], losses, **kwargs):

        if isinstance(losses, tp.Callable):
            name = (
                losses.name
                if isinstance(losses, Loss)
                else utils.lower_snake_case(losses.__name__)
            )
            context += (name,)
            val = utils.inject_dependencies(losses)(**kwargs)

            if isinstance(val, tp.Dict):
                for name, val in val.items():
                    yield context + (name,), val
            else:
                yield context, val

        elif isinstance(losses, (tp.Tuple, tp.List)):
            for loss in losses:
                yield from self.apply_recursive(context, loss, **kwargs)
        elif isinstance(losses, tp.Dict):
            for name, loss in losses.items():
                yield from self.apply_recursive(context + (name,), loss, **kwargs)
        else:
            raise TypeError(f"Invalid type {type(losses)}")

    def get_unique_loss_name(self, context, logs):
        context = list(context)

        if not context[0].endswith("loss"):
            context[0] += "_loss"

        name = "/".join(context)

        if name not in logs:
            return name

        i = 1
        while f"{name}_{i}" in logs:
            i += 1

        return f"{name}_{i}"


class LossMetrics(Metric):
    def call(self, logs):

        count = self.add_parameter("count", initializer=0, trainable=False)
        total = self.add_parameter(
            "total", initializer=jax.tree_map(lambda x: 0.0, logs), trainable=False
        )

        count += 1
        total = jax.tree_multimap(lambda a, b: a + b, total, logs)

        self.update_parameter("count", count)
        self.update_parameter("total", total)

        logs = jax.tree_map(lambda total: total / count, total)

        return logs


class Metrics(Metric):
    def __init__(self, metrics, **kwargs):
        super().__init__(**kwargs)
        self.metrics = metrics

    def call(self, logs, **kwargs):

        # Loss logs
        logs = LossMetrics()(logs)

        # Metric logs
        for context, val in self.apply_recursive((), self.metrics, **kwargs):
            name = "/".join(context)
            name = self.get_unique_metric_name(logs, name)
            logs[name] = val

        return logs

    def apply_recursive(self, context: tp.Tuple[str, ...], metrics, **kwargs):

        if isinstance(metrics, tp.Callable):

            name = (
                metrics.name
                if isinstance(metrics, module.Module)
                else utils.lower_snake_case(metrics.__name__)
            )
            context += (name,)
            value = utils.inject_dependencies(metrics)(**kwargs)

            if isinstance(value, tp.Dict):
                for name, value in value.items():
                    yield context + (name,), value
            else:
                yield context, value

        elif isinstance(metrics, (tp.Tuple, tp.List)):
            for loss in metrics:
                yield from self.apply_recursive(context, loss, **kwargs)
        elif isinstance(metrics, tp.Dict):
            for name, loss in metrics.items():
                yield from self.apply_recursive(context + (name,), loss, **kwargs)
        else:
            raise TypeError(f"Invalid type {type(metrics)}")

    def get_unique_metric_name(self, logs, name):

        if name not in logs:
            return name

        i = 1
        while f"{name}_{i}" in logs:
            i += 1

        return f"{name}_{i}"