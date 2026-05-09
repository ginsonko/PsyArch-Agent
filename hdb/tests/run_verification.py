# -*- coding: utf-8 -*-

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


def main():
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=os.path.dirname(__file__), pattern='test_*.py')
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    print('\n' + '=' * 72)
    print('  HDB 验证总结 / HDB Verification Summary')
    print('=' * 72)
    print(f'  运行 / Run:     {result.testsRun}')
    print(f'  失败 / Failed:  {len(result.failures)}')
    print(f'  错误 / Errors:  {len(result.errors)}')
    if result.wasSuccessful():
        print('  全部通过 / All passed')
        return 0
    print('  存在失败 / There were failures')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
