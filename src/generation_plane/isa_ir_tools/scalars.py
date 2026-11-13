"""Address-free scalar generation using the tensor generator's exact codec."""
from .core import generate_tensor, obj, fail


def generate_scalar(spec, case_seed=0):
    obj(spec, ('name', 'dtype', 'fp8_format', 'fp4_format', 'role',
               'value', 'generate', 'generation'), 'scalar')
    choices = [key for key in ('value', 'generate', 'generation') if key in spec]
    if len(choices) != 1:
        fail('INVALID_PARAMETER', 'scalar', 'choose exactly one value/generate/generation')
    if choices[0] == 'value':
        generation = {'mode': 'numeric', 'pattern': {'kind': 'explicit', 'values': [spec['value']]}}
    else:
        generation = spec[choices[0]]
    tensor = {key: spec[key] for key in ('name', 'dtype', 'fp8_format', 'fp4_format', 'role') if key in spec}
    tensor.update(shape=[1], generation=generation)
    result = generate_tensor(tensor, case_seed)
    # The ordinary codec owns sampling, validation and rounding. Its temporary
    # atom padding is discarded: scalars never publish files or allocate memory.
    return {'name': result['name'], 'dtype': result['dtype'],
            'element bits': result['codec']['element_bits'], 'bits': result['values'][0],
            'generation': result['generation'], 'codec': result['codec']}
