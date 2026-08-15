"""TS-050: 一次进程执行多个 import/调用 scenario 的共享测试工具。

父测试把 scenario 定义（名字 + 代码段）交给一个 fresh interpreter，子进程按
"先查后导"顺序逐个执行：每个 scenario 先检查 forbidden modules 是否已加载
（防顺序污染），再执行自己的 import/调用动作，最后再检查一次，结果累积为
结构化 JSON（scenario/loaded/forbidden_missing/exit_code）输出；父测试解析
JSON 后逐 scenario 断言，参数化 case 从共享结果中取自己的 scenario。

不同 clean state（PYTHONPATH/env 不同）的 scenario 不得合进同一进程——
调用方负责保证一次 run_scenario_batch 内所有 scenario 的起始环境一致。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ScenarioResult = dict[str, Any]

_SCENARIO_SHELL = (
    "import json, os, sys\n"
    "scenarios = json.loads(os.environ.pop('AXDATA_SCENARIOS', '[]'))\n"
    "results = {}\n"
    "for name, code in scenarios:\n"
    "    try:\n"
    "        exec(code, {'results': results, 'scenario_name': name})\n"
    "    except BaseException as exc:\n"
    "        results[name] = {'subprocess_error': repr(exc), 'exit_code': 1}\n"
    "print('AXDATA_RESULTS=' + json.dumps(results, sort_keys=True))\n"
)


def run_scenario_batch(
    scenarios: list[tuple[str, str]],
    *,
    pythonpath: str,
    cwd: Path,
) -> dict[str, ScenarioResult]:
    """在一个 fresh interpreter 中按顺序执行 scenarios，返回 name -> result。

    子进程以非零退出码结束时抛 ``subprocess.CalledProcessError``（与既有
    ``check=True`` 语义一致）；scenario 内部异常由 scenario code 自行记录。
    """

    env = {
        **os.environ,
        "PYTHONPATH": pythonpath,
        "AXDATA_SCENARIOS": json.dumps(scenarios),
    }
    completed = subprocess.run(
        [sys.executable, "-c", _SCENARIO_SHELL],
        check=True,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    marker = "AXDATA_RESULTS="
    return json.loads(completed.stdout[completed.stdout.rindex(marker) + len(marker) :])


def import_family_scenario_code(module_name: str, tracked: list[str]) -> str:
    """构造一个"import module_name 后断言 tracked 未加载"的 scenario 代码段。"""

    return (
        "import importlib\n"
        "import sys\n"
        f"module_name = {module_name!r}\n"
        f"tracked = {tracked!r}\n"
        "pre_loaded = [name for name in tracked if name in sys.modules]\n"
        "try:\n"
        "    importlib.import_module(module_name)\n"
        "    exit_code = 0\n"
        "except BaseException:\n"
        "    exit_code = 1\n"
        "loaded = [name for name in tracked if name in sys.modules]\n"
        "results[scenario_name] = {\n"
        "    'module_loaded': module_name in sys.modules,\n"
        "    'pre_loaded': pre_loaded,\n"
        "    'loaded': loaded,\n"
        "    'forbidden_missing': [name for name in tracked if name not in loaded],\n"
        "    'exit_code': exit_code,\n"
        "}\n"
    )


def run_import_family(
    modules: list[str],
    tracked: list[str],
    *,
    pythonpath: str,
    cwd: Path,
) -> dict[str, ScenarioResult]:
    """一次进程执行一整族 import scenario（每族一个进程）。"""

    scenarios = [(module, import_family_scenario_code(module, tracked)) for module in modules]
    return run_scenario_batch(scenarios, pythonpath=pythonpath, cwd=cwd)
