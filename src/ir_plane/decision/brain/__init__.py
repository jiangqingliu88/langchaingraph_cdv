"""
Decision Brain —— V3 决策学习层（规则 + RL 并行）

V3 在 V2 的语义决策之上加一条学习路径：
  - Rule Engine（确定性）：硬失败（编译错/比对错/环境失败）+ 冷启动语义决策
  - RL Policy（Q-learning）：软决策（覆盖率 gap 下哪个动作提升最大）

用法:
    from src.ir_plane.decision.brain.decision_brain import DecisionBrain
    from src.ir_plane.decision.brain.rl_policy import QLearningPolicy
    from src.ir_plane.decision.brain.state_encoder import encode_state
"""
from .state_encoder import encode_state, decode_state
from .rl_policy import QLearningPolicy, SOFT_ACTIONS
from .decision_brain import DecisionBrain

__all__ = ["encode_state", "decode_state", "QLearningPolicy", "SOFT_ACTIONS",
           "DecisionBrain"]
