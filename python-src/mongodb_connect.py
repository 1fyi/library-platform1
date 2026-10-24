# -*- coding: utf-8 -*-
"""
mongodb_connect.py —— 数据库连接模块（任务五 ST-5.2）

功能：
    1. 统一存放 MongoDB 连接参数（地址、端口、库名、账号、密码）；
    2. 使用 MongoClient 建立连接，并向其它所有模块提供 get_db()；
    3. 提供连接检测、优雅关闭等工具函数。

说明：
    - 默认连接本机 27017 端口的 library 数据库，且不启用认证；
    - 如果任务四已经启用访问控制（--auth），请设置环境变量后再运行：
          Windows PowerShell:
              $env:MONGO_USERNAME="libWriter"
              $env:MONGO_PASSWORD="你的密码"
          Linux / macOS:
              export MONGO_USERNAME=libWriter
              export MONGO_PASSWORD=你的密码
      也可以直接修改下面带“默认值”注释的常量。

作者：课程实训项目
"""

import os
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient
from pymongo.errors import (
    ConfigurationError,
    ConnectionFailure,
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
)

# ---------------------------------------------------------------------------
# 一、连接参数（全部集中在本模块定义，其它文件只调用 get_db()）
# ---------------------------------------------------------------------------
MONGO_HOST = os.getenv("MONGO_HOST", "127.0.0.1")        # 数据库地址
MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))       # 数据库端口
MONGO_DB = os.getenv("MONGO_DB", "library")              # 业务数据库名

# 未启用认证时保持为空字符串即可；启用认证后填写账号密码。
MONGO_USERNAME = os.getenv("MONGO_USERNAME", "")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD", "")
# 账号建立在哪个数据库就填哪个库名（libReader / libWriter 建在 library 库）
MONGO_AUTH_SOURCE = os.getenv("MONGO_AUTH_SOURCE", MONGO_DB)

# 连接超时（毫秒），避免数据库没启动时程序长时间卡住
SERVER_SELECTION_TIMEOUT_MS = 5000

# 东八区，仅用于把 BSON 里的 UTC 时间格式化成易读的北京时间
CST = timezone(timedelta(hours=8))

# 模块级单例，保证整个程序只创建一个连接池
_client = None

# 四个集合名，供各模块统一引用
COLL_BOOKS = "books"
COLL_READERS = "readers"
COLL_BORROW_LOGS = "borrow_logs"
COLL_CATEGORY_STATS = "category_stats"
COLL_BOOK_LOGS = "book_logs"
COLL_BOOK_IN_STOCK = "book_in_stock"


def build_uri():
    """返回当前配置对应的连接字符串，便于打印和排查问题。"""
    if MONGO_USERNAME:
        return "mongodb://%s:%s@%s:%d/%s?authSource=%s" % (
            MONGO_USERNAME,
            "******",
            MONGO_HOST,
            MONGO_PORT,
            MONGO_DB,
            MONGO_AUTH_SOURCE,
        )
    return "mongodb://%s:%d/%s" % (MONGO_HOST, MONGO_PORT, MONGO_DB)


def get_client():
    """获取（并缓存）MongoClient 实例。"""
    global _client
    if _client is None:
        kwargs = {
            "host": MONGO_HOST,
            "port": MONGO_PORT,
            "serverSelectionTimeoutMS": SERVER_SELECTION_TIMEOUT_MS,
            "connectTimeoutMS": SERVER_SELECTION_TIMEOUT_MS,
        }
        if MONGO_USERNAME:
            kwargs["username"] = MONGO_USERNAME
            kwargs["password"] = MONGO_PASSWORD
            kwargs["authSource"] = MONGO_AUTH_SOURCE
        _client = MongoClient(**kwargs)
    return _client


def get_db():
    """获取 library 数据库对象，所有模块都通过它操作集合。"""
    return get_client()[MONGO_DB]


def ping():
    """检测数据库是否可访问，返回 (是否成功, 提示信息)。"""
    try:
        get_client().admin.command("ping")
        info = get_client().server_info()
        return True, "连接成功，MongoDB 版本 %s" % info.get("version", "未知")
    except ServerSelectionTimeoutError:
        return False, (
            "连接超时：请确认 MongoDB 服务已启动，且地址端口为 %s:%d"
            % (MONGO_HOST, MONGO_PORT)
        )
    except OperationFailure as exc:
        return False, "认证或权限失败：%s" % exc
    except (ConnectionFailure, ConfigurationError) as exc:
        return False, "连接失败：%s" % exc


def close():
    """关闭连接（程序退出前调用）。"""
    global _client
    if _client is not None:
        _client.close()
        _client = None


def fmt_dt(value, fmt="%Y-%m-%d"):
    """把 BSON 中取出的 UTC 时间转换成北京时间字符串，便于显示。"""
    if not value:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(CST).strftime(fmt)


def parse_date(text):
    """把 'YYYY-MM-DD' 文本解析成东八区时间；解析失败返回 None。"""
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").replace(tzinfo=CST)
    except ValueError:
        return None


def now():
    """当前北京时间。"""
    return datetime.now(CST)


if __name__ == "__main__":
    # 直接运行本模块时做一次自检
    ok, message = ping()
    print("[连接信息] %s" % build_uri())
    print("[检测结果] %s" % message)
    if ok:
        database = get_db()
        print("[集合列表] %s" % ", ".join(sorted(database.list_collection_names())))
        for name in (COLL_BOOKS, COLL_READERS, COLL_BORROW_LOGS, COLL_CATEGORY_STATS):
            print("  %-15s %d 条" % (name, database[name].count_documents({})))
    close()
