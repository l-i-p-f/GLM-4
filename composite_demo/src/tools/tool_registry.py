"""
This code is the tool registration part. By registering the tool, the model can call the tool.
This code provides extended functionality to the model, enabling it to call and interact with a variety of utilities
through defined interfaces.
"""

from collections.abc import Callable
import copy
import inspect
import json
import traceback
from types import GenericAlias
from typing import get_origin, Annotated
import subprocess

from interface import ToolObservation
from browser import tool_call as browser
from cogview import tool_call as cogview
from python import tool_call as python

ALL_TOOLS = {
    "simple_browser": browser,
    "python": python,
    "cogview": cogview,
}

_TOOL_HOOKS = {}    # 函数名称及函数本身，可直接调用
"""
工具描述组织格式
{
    "name": 工具名称=函数名称
    "description": 工具描述=函数doc注释
    "params": [
        {
            "name": 函数参数名称
            "type": 参数类型
            "description": 参数描述
            "required": 布尔值，标识是否可选参数
        },
        {...},
        ...
    ]
}
"""
_TOOL_DESCRIPTIONS = []


def register_tool(func: Callable):
    """ 注册工具/tool """
    # 函数的名称，注释及变量会被提取用作工具注册
    tool_name = func.__name__
    tool_description = inspect.getdoc(func).strip()
    python_params = inspect.signature(func).parameters
    tool_params = []
    for name, param in python_params.items():
        # 参数注解检查
        annotation = param.annotation
        if annotation is inspect.Parameter.empty:
            raise TypeError(f"Parameter `{name}` missing type annotation")
        if get_origin(annotation) != Annotated:
            raise TypeError(f"Annotation type for `{name}` must be typing.Annotated")

        typ, (description, required) = annotation.__origin__, annotation.__metadata__
        typ: str = str(typ) if isinstance(typ, GenericAlias) else typ.__name__
        if not isinstance(description, str):
            raise TypeError(f"Description for `{name}` must be a string")
        if not isinstance(required, bool):
            raise TypeError(f"Required for `{name}` must be a bool")

        tool_params.append(
            {
                "name": name,
                "description": description,
                "type": typ,
                "required": required,
            }
        )
    tool_def = {
        "name": tool_name,
        "description": tool_description,
        "params": tool_params,
    }
    # print("[registered tool] " + pformat(tool_def))
    _TOOL_HOOKS[tool_name] = func
    _TOOL_DESCRIPTIONS.append(tool_def)

    return func


def dispatch_tool(tool_name: str, code: str, session_id: str) -> list[ToolObservation]:
    """ 分派/调用不同的工具

    :param tool_name: 工具名称
    :param code: 字符串存储的json格式的参数列表，一般为模型的输出
    :param session_id: 会话id

    :return:
    """
    # Dispatch predefined tools
    # 调用系统工具(预定义工具)
    # TODO: 为什么系统工具直接用code, 自定义工具要检查? 输出不同? 还是后续处理?
    if tool_name in ALL_TOOLS:
        return ALL_TOOLS[tool_name](code, session_id)

    # 工具调用的标志符: <|observation|>
    # 移除【字符串末尾】的<|observation|>字符
    code = code.strip().rstrip('<|observation|>').strip()

    # 调用自定义工具
    # Dispatch custom tools
    try:
        tool_params = json.loads(code)
    except json.JSONDecodeError as e:
        err = f"Error decoding JSON: {e}"
        return [ToolObservation("system_error", err)]

    if tool_name not in _TOOL_HOOKS:
        err = f"Tool `{tool_name}` not found. Please use a provided tool."
        return [ToolObservation("system_error", err)]

    # 执行工具调用操作
    tool_hook = _TOOL_HOOKS[tool_name]
    try:
        # 所有输出被强制转换为字符串
        ret: str = tool_hook(**tool_params)
        return [ToolObservation(tool_name, str(ret))]
    except (Exception,):
        err = traceback.format_exc()
        return [ToolObservation("system_error", err)]


def get_tools() -> list[dict]:
    return copy.deepcopy(_TOOL_DESCRIPTIONS)


# Tool Definitions
"""
Tips: 函数的定义，请严格参照示例
- 函数的名称，doc注释及参数会被提取用作工具注册
- 函数参数，使用Annotated类为类型添加额外的元数据
    - 参数类型
    - 参数作用
    - 是否可选参数
"""


# 函数定义时，同时会执行装饰器函数
@register_tool
def random_number_generator(
        seed: Annotated[int, "The random seed used by the generator", True],
        range: Annotated[tuple[int, int], "The range of the generated numbers", True],
) -> int:
    """
    Generates a random number x, s.t. range[0] <= x < range[1]
    """
    if not isinstance(seed, int):
        raise TypeError("Seed must be an integer")
    if not isinstance(range, tuple):
        raise TypeError("Range must be a tuple")
    if not isinstance(range[0], int) or not isinstance(range[1], int):
        raise TypeError("Range must be a tuple of integers")

    import random

    return random.Random(seed).randint(*range)


@register_tool
def get_weather(
        city_name: Annotated[str, "The name of the city to be queried", True],
) -> str:
    """
    Get the current weather for `city_name`
    """

    # 基于该项目提供的天气获取接口: https://github.com/chubin/wttr.in
    if not isinstance(city_name, str):
        raise TypeError("City name must be a string")

    key_selection = {
        "current_condition": [
            "temp_C",
            "FeelsLikeC",
            "humidity",
            "weatherDesc",
            "observation_time",
        ],
    }
    import requests

    try:
        resp = requests.get(f"https://wttr.in/{city_name}?format=j1")
        resp.raise_for_status()
        resp = resp.json()
        ret = {k: {_v: resp[k][0][_v] for _v in v} for k, v in key_selection.items()}
    except (Exception,):
        import traceback

        ret = (
                "Error encountered while fetching weather data!\n" + traceback.format_exc()
        )

    return str(ret)


@register_tool
def get_shell(
        query: Annotated[str, "The command should run in Linux shell", True],
) -> str:
    """
    Use shell to run command
    """
    if not isinstance(query, str):
        raise TypeError("Command must be a string")
    try:
        result = subprocess.run(
            query,
            shell=True,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        return e.stderr


if __name__ == "__main__":
    # print(dispatch_tool("get_shell", {"query": "pwd"}))
    print(get_tools())
