from elegy import types
import typing as tp

import jax.numpy as jnp

from elegy import utils
from elegy.losses.loss import Loss, Reduction


def mean_squared_logarithmic_error(
    y_true: jnp.ndarray, y_pred: jnp.ndarray
) -> jnp.ndarray:
    """
    Computes the mean squared logarithmic error between labels and predictions.

    ```python
    loss = mean(square(log(y_true + 1) - log(y_pred + 1)), axis=-1)
    ```

    Usage:

    ```python
    rng = jax.random.PRNGKey(42)

    y_true = jax.random.randint(rng, shape=(2, 3), minval=0, maxval=2)
    y_pred = jax.random.uniform(rng, shape=(2, 3))

    loss = elegy.losses.mean_squared_logarithmic_error(y_true, y_pred)

    assert loss.shape == (2,)

    first_log = jnp.log(jnp.maximum(y_true, utils.EPSILON) + 1.0)
    second_log = jnp.log(jnp.maximum(y_pred, utils.EPSILON) + 1.0)
    assert jnp.array_equal(loss, jnp.mean(jnp.square(first_log - second_log), axis=-1))
    ```

    Arguments:
        y_true: Ground truth values. shape = `[batch_size, d0, .. dN]`.
        y_pred: The predicted values. shape = `[batch_size, d0, .. dN]`.

    Returns:
        Mean squared logarithmic error values. shape = `[batch_size, d0, .. dN-1]`.
    """

    y_true = y_true.astype(y_pred.dtype)
    first_log = jnp.log(jnp.maximum(y_true, utils.EPSILON) + 1.0)
    second_log = jnp.log(jnp.maximum(y_pred, utils.EPSILON) + 1.0)

    return jnp.mean(jnp.square(first_log - second_log), axis=-1)


class MeanSquaredLogarithmicError(Loss):
    """
    Computes the mean squared logarithmic errors between labels and predictions.

    `loss = mean(square(log(y_true + 1) - log(y_pred + 1)), axis=-1)`

    Usage:

    ```python
    y_true = jnp.array([[0.0, 1.0], [0.0, 0.0]])
    y_pred = jnp.array([[1.0, 1.0], [1.0, 0.0]])

    # Using 'auto'/'sum_over_batch_size' reduction type.
    msle = elegy.losses.MeanSquaredLogarithmicError()

    assert msle(y_true, y_pred) == 0.24022643

    # Calling with 'sample_weight'.
    assert msle(y_true, y_pred, sample_weight=jnp.array([0.7, 0.3])) = 0.12011322

    # Using 'sum' reduction type.
    msle = elegy.losses.MeanSquaredLogarithmicError(reduction=elegy.losses.Reduction.SUM)

    assert msle(y_true, y_pred) == 0.48045287

    # Using 'none' reduction type.
    msle = elegy.losses.MeanSquaredLogarithmicError(reduction=elegy.losses.Reduction.NONE)

    assert jnp.equal(msle(y_true, y_pred), jnp.array([0.24022643, 0.24022643])).all()
    ```
    Usage with the Elegy API:

    ```python
    model = elegy.Model(
        module_fn,
        loss=elegy.losses.MeanSquaredLogarithmicError(),
        metrics=elegy.metrics.Mean(),
    )
    ```
    """

    def __init__(
        self,
        reduction: tp.Optional[Reduction] = None,
        weight: tp.Optional[float] = None,
        on: tp.Optional[types.IndexLike] = None,
        **kwargs
    ):
        """
        Initializes `Mean` class.

        Arguments:
            reduction: (Optional) Type of `elegy.losses.Reduction` to apply to
                loss. Default value is `SUM_OVER_BATCH_SIZE`. For almost all cases
                this defaults to `SUM_OVER_BATCH_SIZE`.
            weight: Optional weight contribution for the total loss. Defaults to `1`.
            on: A string or integer, or iterable of string or integers, that
                indicate how to index/filter the `y_true` and `y_pred`
                arguments before passing them to `call`. For example if `on = "a"` then
                `y_true = y_true["a"]`. If `on` is an iterable
                the structures will be indexed iteratively, for example if `on = ["a", 0, "b"]`
                then `y_true = y_true["a"][0]["b"]`, same for `y_pred`. For more information
                check out [Keras-like behavior](https://poets-ai.github.io/elegy/guides/modules-losses-metrics/#keras-like-behavior).
        """

        return super().__init__(reduction=reduction, weight=weight, on=on, **kwargs)

    def call(
        self,
        y_true: jnp.ndarray,
        y_pred: jnp.ndarray,
        sample_weight: tp.Optional[
            jnp.ndarray
        ] = None,  # not used, __call__ handles it, left for documentation purposes.
    ) -> jnp.ndarray:
        """
        Invokes the `MeanSquaredLogarithmicError` instance.

        Arguments:
            y_true: Ground truth values. shape = `[batch_size, d0, .. dN]`, except
                sparse loss functions such as sparse categorical crossentropy where
                shape = `[batch_size, d0, .. dN-1]`
            y_pred: The predicted values. shape = `[batch_size, d0, .. dN]`
            sample_weight: Optional `sample_weight` acts as a
                coefficient for the loss. If a scalar is provided, then the loss is
                simply scaled by the given value. If `sample_weight` is a tensor of size
                `[batch_size]`, then the total loss for each sample of the batch is
                rescaled by the corresponding element in the `sample_weight` vector. If
                the shape of `sample_weight` is `[batch_size, d0, .. dN-1]` (or can be
                broadcasted to this shape), then each loss element of `y_pred` is scaled
                by the corresponding value of `sample_weight`. (Note on`dN-1`: all loss
                functions reduce by 1 dimension, usually axis=-1.)

        Returns:
            Weighted loss float `Tensor`. If `reduction` is `NONE`, this has
                shape `[batch_size, d0, .. dN-1]`; otherwise, it is scalar. (Note `dN-1`
                because all loss functions reduce by 1 dimension, usually axis=-1.)

        Raises:
            ValueError: If the shape of `sample_weight` is invalid.
        """
        return mean_squared_logarithmic_error(y_true, y_pred)
