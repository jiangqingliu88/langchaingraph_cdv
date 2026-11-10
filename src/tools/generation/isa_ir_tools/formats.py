"""Reversible human byte hex and 256-bit readmemh text."""
def byte_hex(data):
    return ''.join(data[i:i+16].hex()+' \n' for i in range(0,len(data),16))

def memh(data):
    if len(data)%32:
        raise ValueError('memh payload must contain whole 32-byte atoms')
    return ''.join(data[i:i+32][::-1].hex()+'\n' for i in range(0,len(data),32))


def from_memh(text):
    lines=text.splitlines()
    if any(len(line)!=64 or any(c not in '0123456789abcdef' for c in line) for line in lines):
        raise ValueError('memh requires exactly 64 lowercase hex digits per line')
    return b''.join(bytes.fromhex(line)[::-1] for line in lines)
