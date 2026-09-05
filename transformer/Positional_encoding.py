import numpy as np

def positional_encoding(max_len, d_model):
    """
    生成位置编码
    max_len: 最大序列长度
    d_model: 词向量的维度
    """
    pe = np.zeros((max_len, d_model))
    position = np.arange(max_len)[:, np.newaxis]
    # 计算除数项，用于生成不同频率的正弦/余弦波
    div_term = np.exp(np.arange(0, d_model, 2) * -(np.log(10000.0) / d_model))
    # 偶数索引用sin，奇数索引用cos
    pe[:, 0::2] = np.sin(position * div_term)
    pe[:, 1::2] = np.cos(position * div_term)
    return pe

#示例：生成一个最大长度100，维度512的位置编码
pe = positional_encoding(100, 512)