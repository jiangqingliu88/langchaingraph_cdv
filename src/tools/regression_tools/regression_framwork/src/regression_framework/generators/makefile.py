# src/regression_framework/generators/makefile.py
import os
from ..core.logging_config import get_logger

logger = get_logger(__name__)

class MakefileGenerator:
    def generate(self, config: dict, root_dir: str, mode: str):
        os.makedirs(root_dir, exist_ok=True)
        logger.info(f"Creating Makefile in {root_dir}")
        with open(os.path.join(root_dir, 'Makefile'), 'w', encoding='utf-8') as f:
            f.write(".PHONY: all build test clean\n\n")
            f.write("all: build test\n\n")
            f.write("build:\n")
            for build in config.get('builds', []):
                f.write(f"\tcd build_{build['name']} && ./build.sh\n")
            f.write("\ntest:\n")
            for test in config.get('tests', []):
                build_name = test.get('build', 'build_base')
                if isinstance(build_name, dict):
                    build_name = build_name.get('name', 'build_base')
                test_name = test['name']
                seed = test.get('local_vars', {}).get('SEED', None)
                subdir = f"test_{test_name}_seed_{seed}" if seed is not None else f"test_{test_name}"
                f.write(f"\tcd build_{build_name}/{subdir} && ./sim.sh\n")
            f.write("\nclean:\n")
            f.write("\trm -rf build_* test_*\n")