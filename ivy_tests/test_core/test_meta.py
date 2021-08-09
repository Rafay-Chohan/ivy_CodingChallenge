"""
Collection of tests for templated meta functions
"""

# global
import pytest
import numpy as np

# local
import ivy
import ivy.numpy
import ivy_tests.helpers as helpers


# First Order #
# ------------#

# fomaml step unique vars
@pytest.mark.parametrize(
    "inner_grad_steps", [1, 2, 3])
@pytest.mark.parametrize(
    "with_outer_cost_fn", [True, False])
@pytest.mark.parametrize(
    "average_across_steps", [True, False])
@pytest.mark.parametrize(
    "num_tasks", [1, 2])
@pytest.mark.parametrize(
    "return_inner_v", ['first', 'all', False])
def test_fomaml_step_unique_vars(dev_str, call, inner_grad_steps, with_outer_cost_fn, average_across_steps, num_tasks,
                                 return_inner_v):

    if call in [helpers.np_call, helpers.jnp_call]:
        # Numpy does not support gradients, and jax does not support gradients on custom nested classes
        pytest.skip()

    # config
    inner_learning_rate = 1e-2

    # create variables
    variables = ivy.Container({'latent': ivy.variable(ivy.repeat(ivy.array([0.]), num_tasks, 0)),
                               'weight': ivy.variable(ivy.repeat(ivy.array([1.]), num_tasks, 0))})

    # batch
    batch = ivy.Container({'x': ivy.arange(num_tasks+1, 1, dtype_str='float32')})

    # inner cost function
    def inner_cost_fn(batch_in, v):
        cost = 0
        for sub_batch_in, sub_v in zip(batch_in.unstack(0, keepdims=True), v.unstack(0, keepdims=True)):
            cost = cost - (sub_batch_in['x'] * sub_v['latent'] * sub_v['weight'])[0]
        return cost

    # outer cost function
    def outer_cost_fn(batch_in, v):
        cost = 0
        for sub_batch_in, sub_v in zip(batch_in.unstack(0, keepdims=True), v.unstack(0, keepdims=True)):
            cost = cost + (sub_batch_in['x'] * sub_v['latent'] * sub_v['weight'])[0]
        return cost

    # numpy
    weight_np = ivy.to_numpy(variables.weight[0:1])
    latent_np = ivy.to_numpy(variables.latent[0:1])
    batch_np = batch.map(lambda x, kc: ivy.to_numpy(x))

    # true gradient
    all_outer_grads = list()
    for sub_batch in batch_np.unstack(0, True, num_tasks):
        all_outer_grads.append(
            [(-i*inner_learning_rate*weight_np*sub_batch['x'][0]**2 - sub_batch['x'][0]*latent_np) *
             (-1 if with_outer_cost_fn else 1) for i in range(inner_grad_steps+1)])
    if average_across_steps:
        true_weight_grad = sum([sum(og) / len(og) for og in all_outer_grads]) / num_tasks
    else:
        true_weight_grad = sum([og[-1] for og in all_outer_grads]) / num_tasks

    # meta update
    rets = ivy.fomaml_step(
        batch, inner_cost_fn, outer_cost_fn if with_outer_cost_fn else None, variables,
        inner_grad_steps, inner_learning_rate, average_across_steps=average_across_steps,
        inner_v='latent', outer_v='weight', return_inner_v=return_inner_v)
    outer_grads = rets[1]
    assert np.allclose(ivy.to_numpy(outer_grads.weight[0]), np.array(true_weight_grad))
    if return_inner_v:
        inner_v_rets = rets[2]
        assert isinstance(inner_v_rets[0], ivy.Container)


# fomaml step shared vars
@pytest.mark.parametrize(
    "inner_grad_steps", [1, 2, 3])
@pytest.mark.parametrize(
    "with_outer_cost_fn", [True, False])
@pytest.mark.parametrize(
    "average_across_steps", [True, False])
@pytest.mark.parametrize(
    "num_tasks", [1, 2])
@pytest.mark.parametrize(
    "return_inner_v", ['first', 'all', False])
def test_fomaml_step_shared_vars(dev_str, call, inner_grad_steps, with_outer_cost_fn, average_across_steps, num_tasks,
                                 return_inner_v):

    if call in [helpers.np_call, helpers.jnp_call, helpers.mx_call]:
        # Numpy does not support gradients, jax does not support gradients on custom nested classes,
        # and mxnet does not support only_inputs argument to mx.autograd.grad
        pytest.skip()

    # config
    inner_learning_rate = 1e-2

    # create variable
    variables = ivy.Container({'latent': ivy.variable(ivy.repeat(ivy.array([1.]), num_tasks, 0))})

    # batch
    batch = ivy.Container({'x': ivy.arange(num_tasks+1, 1, dtype_str='float32')})

    # inner cost function
    def inner_cost_fn(batch_in, v):
        cost = 0
        for sub_batch_in, sub_v in zip(batch_in.unstack(0, keepdims=True), v.unstack(0, keepdims=True)):
            cost = cost - (sub_batch_in['x'] * sub_v['latent'] ** 2)[0]
        return cost

    # outer cost function
    def outer_cost_fn(batch_in, v):
        cost = 0
        for sub_batch_in, sub_v in zip(batch_in.unstack(0, keepdims=True), v.unstack(0, keepdims=True)):
            cost = cost + (sub_batch_in['x'] * sub_v['latent'] ** 2)[0]
        return cost

    # numpy
    latent_np = ivy.to_numpy(variables.latent[0:1])
    batch_np = batch.map(lambda x, kc: ivy.to_numpy(x))

    # loss grad function
    def loss_grad_fn(sub_batch_in, w_in, outer=False):
        return (1 if (with_outer_cost_fn and outer) else -1) * 2 * sub_batch_in['x'][0] * w_in

    # true gradient
    true_outer_grads = list()
    for sub_batch in batch_np.unstack(0, True, num_tasks):
        ws = list()
        grads = list()
        ws.append(latent_np)
        for step in range(inner_grad_steps):
            update_grad = loss_grad_fn(sub_batch, ws[-1])
            w = ws[-1] - inner_learning_rate * update_grad
            if with_outer_cost_fn:
                grads.append(loss_grad_fn(sub_batch, ws[-1], outer=True))
            else:
                grads.append(update_grad)
            ws.append(w)
        if with_outer_cost_fn:
            grads.append(loss_grad_fn(sub_batch, ws[-1], outer=True))
        else:
            grads.append(loss_grad_fn(sub_batch, ws[-1]))

        # true outer grad
        if average_across_steps:
            true_outer_grad = sum(grads) / len(grads)
        else:
            true_outer_grad = grads[-1]
        true_outer_grads.append(true_outer_grad)
    true_outer_grad = sum(true_outer_grads) / len(true_outer_grads)

    # meta update
    rets = ivy.fomaml_step(
        batch, inner_cost_fn, outer_cost_fn if with_outer_cost_fn else None, variables,
        inner_grad_steps, inner_learning_rate, average_across_steps=average_across_steps, return_inner_v=return_inner_v)
    outer_grads = rets[1]
    assert np.allclose(ivy.to_numpy(outer_grads.latent[0]), np.array(true_outer_grad))
    if return_inner_v:
        inner_v_rets = rets[2]
        assert isinstance(inner_v_rets[0], ivy.Container)


# fomaml step overlapping vars
@pytest.mark.parametrize(
    "inner_grad_steps", [1, 2, 3])
@pytest.mark.parametrize(
    "with_outer_cost_fn", [True, False])
@pytest.mark.parametrize(
    "average_across_steps", [True, False])
@pytest.mark.parametrize(
    "num_tasks", [1, 2])
@pytest.mark.parametrize(
    "return_inner_v", ['first', 'all', False])
def test_fomaml_step_overlapping_vars(dev_str, call, inner_grad_steps, with_outer_cost_fn, average_across_steps,
                                      num_tasks, return_inner_v):

    if call in [helpers.np_call, helpers.jnp_call, helpers.mx_call]:
        # Numpy does not support gradients, jax does not support gradients on custom nested classes,
        # and mxnet does not support only_inputs argument to mx.autograd.grad
        pytest.skip()

    # config
    inner_learning_rate = 1e-2

    # create variables
    variables = ivy.Container({'latent': ivy.variable(ivy.repeat(ivy.array([0.]), num_tasks, 0)),
                               'weight': ivy.variable(ivy.repeat(ivy.array([1.]), num_tasks, 0))})

    # batch
    batch = ivy.Container({'x': ivy.arange(num_tasks+1, 1, dtype_str='float32')})

    # inner cost function
    def inner_cost_fn(batch_in, v):
        cost = 0
        for sub_batch_in, sub_v in zip(batch_in.unstack(0, keepdims=True), v.unstack(0, keepdims=True)):
            cost = cost - (sub_batch_in['x'] * sub_v['latent'] * sub_v['weight'])[0]
        return cost

    # outer cost function
    def outer_cost_fn(batch_in, v):
        cost = 0
        for sub_batch_in, sub_v in zip(batch_in.unstack(0, keepdims=True), v.unstack(0, keepdims=True)):
            cost = cost + (sub_batch_in['x'] * sub_v['latent'] * sub_v['weight'])[0]
        return cost

    # numpy
    latent_np = ivy.to_numpy(variables.latent[0:1])
    weight_np = ivy.to_numpy(variables.weight[0:1])
    batch_np = batch.map(lambda x, kc: ivy.to_numpy(x))

    # true gradient
    all_outer_grads = list()
    for sub_batch in batch_np.unstack(0, True, num_tasks):
        all_outer_grads.append(
            [(-i*inner_learning_rate*weight_np*sub_batch['x'][0]**2 - sub_batch['x'][0]*latent_np) *
             (-1 if with_outer_cost_fn else 1) for i in range(inner_grad_steps+1)])
    if average_across_steps:
        true_weight_grad = sum([sum(og) / len(og) for og in all_outer_grads]) / num_tasks
    else:
        true_weight_grad = sum([og[-1] for og in all_outer_grads]) / num_tasks

    # true latent gradient
    true_latent_grad = np.array([(-1-(num_tasks-1)/2)*(-1 if with_outer_cost_fn else 1)])

    # meta update
    rets = ivy.fomaml_step(
        batch, inner_cost_fn, outer_cost_fn if with_outer_cost_fn else None, variables,
        inner_grad_steps, inner_learning_rate, average_across_steps=average_across_steps, inner_v='latent',
        return_inner_v=return_inner_v)
    outer_grads = rets[1]
    assert np.allclose(ivy.to_numpy(outer_grads.weight[0]), np.array(true_weight_grad))
    assert np.allclose(ivy.to_numpy(outer_grads.latent[0]), np.array(true_latent_grad))
    if return_inner_v:
        inner_v_rets = rets[2]
        assert isinstance(inner_v_rets[0], ivy.Container)


# reptile step
@pytest.mark.parametrize(
    "inner_grad_steps", [1, 2, 3])
@pytest.mark.parametrize(
    "num_tasks", [1, 2])
@pytest.mark.parametrize(
    "return_inner_v", ['first', 'all', False])
def test_reptile_step(dev_str, call, inner_grad_steps, num_tasks, return_inner_v):

    if call in [helpers.np_call, helpers.jnp_call, helpers.mx_call]:
        # Numpy does not support gradients, jax does not support gradients on custom nested classes,
        # and mxnet does not support only_inputs argument to mx.autograd.grad
        pytest.skip()

    # config
    inner_learning_rate = 1e-2

    # create variable
    variables = ivy.Container({'latent': ivy.variable(ivy.repeat(ivy.array([1.]), num_tasks, 0))})

    # batch
    batch = ivy.Container({'x': ivy.arange(num_tasks+1, 1, dtype_str='float32')})

    # inner cost function
    def inner_cost_fn(batch_in, v):
        cost = 0
        for sub_batch_in, sub_v in zip(batch_in.unstack(0, keepdims=True), v.unstack(0, keepdims=True)):
            cost = cost - (sub_batch_in['x'] * sub_v['latent'] ** 2)[0]
        return cost

    # numpy
    latent_np = ivy.to_numpy(variables.latent[0:1])
    batch_np = batch.map(lambda x, kc: ivy.to_numpy(x))

    # loss grad function
    def loss_grad_fn(sub_batch_in, w_in, outer=False):
        return -2 * sub_batch_in['x'][0] * w_in

    # true gradient
    true_outer_grads = list()
    for sub_batch in batch_np.unstack(0, True, num_tasks):
        ws = list()
        grads = list()
        ws.append(latent_np)
        for step in range(inner_grad_steps):
            update_grad = loss_grad_fn(sub_batch, ws[-1])
            w = ws[-1] - inner_learning_rate * update_grad
            grads.append(update_grad)
            ws.append(w)
        grads.append(loss_grad_fn(sub_batch, ws[-1]))

        # true outer grad
        true_outer_grad = sum(grads) / len(grads)
        true_outer_grads.append(true_outer_grad)
    true_outer_grad = (sum(true_outer_grads) / len(true_outer_grads)) / inner_learning_rate

    # meta update
    rets = ivy.reptile_step(batch, inner_cost_fn, variables, inner_grad_steps, inner_learning_rate,
                            return_inner_v=return_inner_v)
    outer_grads = rets[1]
    assert np.allclose(ivy.to_numpy(outer_grads.latent[0]), np.array(true_outer_grad))
    if return_inner_v:
        inner_v_rets = rets[2]
        assert isinstance(inner_v_rets[0], ivy.Container)


# Second Order #
# -------------#

# maml step unique vars
@pytest.mark.parametrize(
    "inner_grad_steps", [1, 2, 3])
@pytest.mark.parametrize(
    "with_outer_cost_fn", [True, False])
@pytest.mark.parametrize(
    "average_across_steps", [True, False])
@pytest.mark.parametrize(
    "num_tasks", [1, 2])
@pytest.mark.parametrize(
    "return_inner_v", ['first', 'all', False])
def test_maml_step_unique_vars(dev_str, call, inner_grad_steps, with_outer_cost_fn, average_across_steps, num_tasks,
                               return_inner_v):

    if call in [helpers.tf_call, helpers.tf_graph_call]:
        pytest.skip()

    if call in [helpers.np_call, helpers.jnp_call, helpers.mx_call]:
        # Numpy does not support gradients, jax does not support gradients on custom nested classes,
        # and mxnet does not support only_inputs argument to mx.autograd.grad
        pytest.skip()

    # config
    inner_learning_rate = 1e-2

    # create variables
    variables = ivy.Container({'latent': ivy.variable(ivy.repeat(ivy.array([0.]), num_tasks, 0)),
                               'weight': ivy.variable(ivy.repeat(ivy.array([1.]), num_tasks, 0))})

    # batch
    batch = ivy.Container({'x': ivy.arange(num_tasks+1, 1, dtype_str='float32')})

    # inner cost function
    def inner_cost_fn(batch_in, v):
        cost = 0
        for sub_batch_in, sub_v in zip(batch_in.unstack(0, keepdims=True), v.unstack(0, keepdims=True)):
            cost = cost - (sub_batch_in['x'] * sub_v['latent'] * sub_v['weight'])[0]
        return cost

    # outer cost function
    def outer_cost_fn(batch_in, v):
        cost = 0
        for sub_batch_in, sub_v in zip(batch_in.unstack(0, keepdims=True), v.unstack(0, keepdims=True)):
            cost = cost + (sub_batch_in['x'] * sub_v['latent'] * sub_v['weight'])[0]
        return cost

    # numpy
    weight_np = ivy.to_numpy(variables.weight[0:1])
    latent_np = ivy.to_numpy(variables.latent[0:1])
    batch_np = batch.map(lambda x, kc: ivy.to_numpy(x))

    # true gradient
    all_outer_grads = list()
    for sub_batch in batch_np.unstack(0, True, num_tasks):
        all_outer_grads.append(
            [(-2*i*inner_learning_rate*weight_np*sub_batch['x'][0]**2 - sub_batch['x'][0]*latent_np) *
             (-1 if with_outer_cost_fn else 1) for i in range(inner_grad_steps+1)])
    if average_across_steps:
        true_outer_grad = sum([sum(og) / len(og) for og in all_outer_grads]) / num_tasks
    else:
        true_outer_grad = sum([og[-1] for og in all_outer_grads]) / num_tasks

    # meta update
    rets = ivy.maml_step(
        batch, inner_cost_fn, outer_cost_fn if with_outer_cost_fn else None, variables,
        inner_grad_steps, inner_learning_rate, average_across_steps=average_across_steps,
        inner_v='latent', outer_v='weight', return_inner_v=return_inner_v)
    outer_grads = rets[1]
    assert np.allclose(ivy.to_numpy(outer_grads.weight[0]), np.array(true_outer_grad))
    if return_inner_v:
        inner_v_rets = rets[2]
        assert isinstance(inner_v_rets[0], ivy.Container)


# maml step shared vars
@pytest.mark.parametrize(
    "inner_grad_steps", [1, 2, 3])
@pytest.mark.parametrize(
    "with_outer_cost_fn", [True, False])
@pytest.mark.parametrize(
    "average_across_steps", [True, False])
@pytest.mark.parametrize(
    "num_tasks", [1, 2])
@pytest.mark.parametrize(
    "return_inner_v", ['first', 'all', False])
def test_maml_step_shared_vars(dev_str, call, inner_grad_steps, with_outer_cost_fn, average_across_steps, num_tasks,
                               return_inner_v):

    if call in [helpers.np_call, helpers.jnp_call, helpers.mx_call]:
        # Numpy does not support gradients, jax does not support gradients on custom nested classes,
        # and mxnet does not support only_inputs argument to mx.autograd.grad
        pytest.skip()

    # config
    inner_learning_rate = 1e-2

    # create variable
    variables = ivy.Container({'latent': ivy.variable(ivy.repeat(ivy.array([1.]), num_tasks, 0))})

    # batch
    batch = ivy.Container({'x': ivy.arange(num_tasks+1, 1, dtype_str='float32')})

    # inner cost function
    def inner_cost_fn(batch_in, v):
        cost = 0
        for sub_batch_in, sub_v in zip(batch_in.unstack(0, keepdims=True), v.unstack(0, keepdims=True)):
            cost = cost - (sub_batch_in['x'] * sub_v['latent'] ** 2)[0]
        return cost

    # outer cost function
    def outer_cost_fn(batch_in, v):
        cost = 0
        for sub_batch_in, sub_v in zip(batch_in.unstack(0, keepdims=True), v.unstack(0, keepdims=True)):
            cost = cost + (sub_batch_in['x'] * sub_v['latent'] ** 2)[0]
        return cost

    # numpy
    variables_np = variables.map(lambda x, kc: ivy.to_numpy(x))
    batch_np = batch.map(lambda x, kc: ivy.to_numpy(x))

    # loss grad function
    def loss_grad_fn(sub_batch_in, w_in, outer=False):
        return (1 if (with_outer_cost_fn and outer) else -1) * 2*sub_batch_in['x'][0]*w_in
    
    # update grad function
    def update_grad_fn(w_init, sub_batch_in, num_steps, average=False):
        terms = [0]*num_steps + [1]
        collection_of_terms = [terms]
        for s in range(num_steps):
            rhs = [t*2*sub_batch_in['x'][0] for t in terms]
            rhs.pop(0)
            rhs.append(0)
            terms = [t + rh for t, rh in zip(terms, rhs)]
            collection_of_terms.append([t for t in terms])
        if average:
            return [sum([t*inner_learning_rate**(num_steps-i) for i, t in enumerate(tms)]) * w_init.latent
                    for tms in collection_of_terms]
        return sum([t*inner_learning_rate**(num_steps-i) for i, t in enumerate(terms)]) * w_init.latent
    
    # true gradient
    true_outer_grads = list()
    for sub_batch in batch_np.unstack(0, True, num_tasks):
        ws = list()
        grads = list()
        ws.append(variables_np)
        for step in range(inner_grad_steps):
            update_grad = loss_grad_fn(sub_batch, ws[-1])
            w = ws[-1] - inner_learning_rate * update_grad
            if with_outer_cost_fn:
                grads.append(loss_grad_fn(sub_batch, ws[-1], outer=True))
            else:
                grads.append(update_grad)
            ws.append(w)
        if with_outer_cost_fn:
            grads.append(loss_grad_fn(sub_batch, ws[-1], outer=True))
        else:
            grads.append(loss_grad_fn(sub_batch, ws[-1]))
    
        # true outer grad
        if average_across_steps:
            true_outer_grad =\
                 sum([ig.latent*ug for ig, ug in
                      zip(grads, update_grad_fn(variables_np, sub_batch, inner_grad_steps, average=True))]) / len(grads)
        else:
            true_outer_grad = update_grad_fn(variables_np, sub_batch, inner_grad_steps) * grads[-1].latent
        true_outer_grads.append(true_outer_grad)
    true_outer_grad = sum(true_outer_grads) / len(true_outer_grads)

    # meta update
    rets = ivy.maml_step(
        batch, inner_cost_fn, outer_cost_fn if with_outer_cost_fn else None, variables,
        inner_grad_steps, inner_learning_rate, average_across_steps=average_across_steps, return_inner_v=return_inner_v)
    outer_grads = rets[1]
    assert np.allclose(ivy.to_numpy(outer_grads.latent[0]), true_outer_grad[0])
    if return_inner_v:
        inner_v_rets = rets[2]
        assert isinstance(inner_v_rets[0], ivy.Container)


# maml step overlapping vars
@pytest.mark.parametrize(
    "inner_grad_steps", [1, 2, 3])
@pytest.mark.parametrize(
    "with_outer_cost_fn", [True, False])
@pytest.mark.parametrize(
    "average_across_steps", [True, False])
@pytest.mark.parametrize(
    "num_tasks", [1, 2])
@pytest.mark.parametrize(
    "return_inner_v", ['first', 'all', False])
def test_maml_step_overlapping_vars(dev_str, call, inner_grad_steps, with_outer_cost_fn, average_across_steps,
                                    num_tasks, return_inner_v):

    if call in [helpers.np_call, helpers.jnp_call, helpers.mx_call]:
        # Numpy does not support gradients, jax does not support gradients on custom nested classes,
        # and mxnet does not support only_inputs argument to mx.autograd.grad
        pytest.skip()

    # config
    inner_learning_rate = 1e-2

    # create variables
    variables = ivy.Container({'latent': ivy.variable(ivy.repeat(ivy.array([0.]), num_tasks, 0)),
                               'weight': ivy.variable(ivy.repeat(ivy.array([1.]), num_tasks, 0))})

    # batch
    batch = ivy.Container({'x': ivy.arange(num_tasks+1, 1, dtype_str='float32')})

    # inner cost function
    def inner_cost_fn(batch_in, v):
        cost = 0
        for sub_batch_in, sub_v in zip(batch_in.unstack(0, keepdims=True), v.unstack(0, keepdims=True)):
            cost = cost - (sub_batch_in['x'] * sub_v['latent'] * sub_v['weight'])[0]
        return cost

    # outer cost function
    def outer_cost_fn(batch_in, v):
        cost = 0
        for sub_batch_in, sub_v in zip(batch_in.unstack(0, keepdims=True), v.unstack(0, keepdims=True)):
            cost = cost + (sub_batch_in['x'] * sub_v['latent'] * sub_v['weight'])[0]
        return cost

    # numpy
    latent_np = ivy.to_numpy(variables.latent)
    weight_np = ivy.to_numpy(variables.weight)
    batch_np = batch.map(lambda x, kc: ivy.to_numpy(x))

    # true weight gradient
    all_outer_grads = list()
    for sub_batch in batch_np.unstack(0, True, num_tasks):
        all_outer_grads.append(
            [(-2*i*inner_learning_rate*weight_np*sub_batch['x'][0]**2 - sub_batch['x'][0]*latent_np) *
             (-1 if with_outer_cost_fn else 1) for i in range(inner_grad_steps+1)])
    if average_across_steps:
        true_weight_grad = sum([sum(og) / len(og) for og in all_outer_grads]) / num_tasks
    else:
        true_weight_grad = sum([og[-1] for og in all_outer_grads]) / num_tasks

    # true latent gradient
    true_latent_grad = np.array([(-1-(num_tasks-1)/2)*(-1 if with_outer_cost_fn else 1)])

    # meta update
    rets = ivy.maml_step(
        batch, inner_cost_fn, outer_cost_fn if with_outer_cost_fn else None, variables,
        inner_grad_steps, inner_learning_rate, average_across_steps=average_across_steps, inner_v='latent',
        return_inner_v=return_inner_v)
    outer_grads = rets[1]
    assert np.allclose(ivy.to_numpy(outer_grads.weight[0]), np.array(true_weight_grad))
    assert np.allclose(ivy.to_numpy(outer_grads.latent[0]), np.array(true_latent_grad))
    if return_inner_v:
        inner_v_rets = rets[2]
        assert isinstance(inner_v_rets[0], ivy.Container)
