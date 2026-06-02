# 列出 smoke 标签的测试
python Verify_run.py --tags smoke --list

# 运行 smoke 测试
python Verify_run.py --tags smoke

# 运行多个标签
python Verify_run.py --tags smoke,sanity,functional

# 运行单个测试
python Verify_run.py --test alu_random_test

# 指定 seed
python Verify_run.py --test alu_random_test --seed 12345

# 并行运行
python Verify_run.py --tags functional --parallel 8

# 仅编译
python Verify_run.py --builds

# 强制重新编译
python Verify_run.py --tags smoke --force

# 干运行
python Verify_run.py --tags stress --dry-run