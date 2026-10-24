# -*- coding: utf-8 -*-
"""
main.py —— 菜单式命令行主程序（任务五 ST-5.5）

启动后：
    1. 打印数据库连接状态与各集合文档总数；
    2. 提供 16 个功能项，覆盖检索、统计、新增、更新、删除、借阅管理；
    3. 每次数据变更后打印受影响文档数；
    4. 查询无结果时给出明确提示；
    5. 退出前关闭数据库连接。

运行：
    python main.py
"""

import sys

from pymongo.errors import PyMongoError

from book_manager import BookManager, print_books
from borrow_manager import BorrowManager, print_logs
from mongodb_connect import (
    COLL_BOOKS,
    COLL_BORROW_LOGS,
    COLL_CATEGORY_STATS,
    COLL_READERS,
    build_uri,
    close,
    fmt_dt,
    get_db,
    ping,
)
from reader_manager import ReaderManager, print_readers
from stat_manager import StatManager

MENU = """
==================== 图书情报检索与统计平台 ====================
  1. 图书组合检索（书名/作者/类别/价格/评分/标签）
  2. 按 ISBN 精确查询
  3. 评分排行榜 Top N
  4. 热门图书榜 Top N（按累计借阅次数）
  5. 新增图书（insert_one）
  6. 调整库存（update_one + $inc）
  7. 按类别打折（updateMany + $mul）
  8. 删除图书（delete_one）
  9. 读者查询（姓名/证号/学院/等级）
 10. 读者统计（学院人数 / 等级分布）
 11. 借阅登记（写借阅流水 + 扣库存）
 12. 归还处理（改流水状态 + 还库存）
 13. 逾期查询
 14. 分类统计报表（$group）
 15. 借阅趋势（$year + $dateToString）
 16. 活跃读者榜 / 学院借阅排行（$lookup）
 17. 统计结果落库 category_stats（$merge）
 18. 借阅状态汇总 / 最近流水
  0. 退出
================================================================
"""


def ask(prompt, default=None):
    """带默认值的输入；直接回车返回默认值。"""
    tip = "%s" % prompt
    if default not in (None, ""):
        tip += "（默认 %s）" % default
    value = input(tip + "：").strip()
    if value == "":
        return default
    return value


def ask_float(prompt, default=None):
    value = ask(prompt, default)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        print("[提示] 输入的不是数字，已忽略该条件。")
        return None


def show_counts(db):
    """打印各集合文档总数。"""
    print("\n[数据概况]")
    counts = [
        ("books（图书）", db[COLL_BOOKS]),
        ("readers（读者）", db[COLL_READERS]),
        ("borrow_logs（借阅流水）", db[COLL_BORROW_LOGS]),
        ("category_stats（统计结果）", db[COLL_CATEGORY_STATS]),
    ]
    for label, collection in counts:
        print("  %-30s %4d 条" % (label, collection.count_documents({})))


class Application:
    """把各功能模块组装成菜单程序。"""

    def __init__(self):
        self.db = get_db()
        self.books = BookManager(self.db)
        self.readers = ReaderManager(self.db)
        self.borrows = BorrowManager(self.db)
        self.stats = StatManager(self.db)

    # ------------------------------------------------------------------
    # 1. 图书组合检索
    # ------------------------------------------------------------------
    def menu_search_books(self):
        print("\n--- 图书组合检索（不需要的条件直接回车跳过）---")
        keyword = ask("书名/作者/出版社关键词")
        category = ask("类别（如 计算机/文学/数学/经济管理/外语）")
        price_min = ask_float("最低价格")
        price_max = ask_float("最高价格")
        rating_min = ask_float("最低评分")
        tags_text = ask("标签（多个用逗号分隔，要求全部包含）")
        limit = ask("最多显示条数", "20")
        tags = [item.strip() for item in (tags_text or "").split(",") if item.strip()]

        rows = self.books.search(
            keyword=keyword or None,
            category=category or None,
            price_min=price_min,
            price_max=price_max,
            rating_min=rating_min,
            tags=tags,
            limit=int(limit) if str(limit).isdigit() else 0,
        )
        print_books(rows, limit=20)

    # ------------------------------------------------------------------
    # 2. ISBN 精确查询
    # ------------------------------------------------------------------
    def menu_find_isbn(self):
        isbn = ask("请输入 ISBN")
        book = self.books.get_by_isbn(isbn)
        if not book:
            print("[提示] 没有找到 ISBN 为 %s 的图书。" % isbn)
            return
        print("\n[查询结果]")
        for key in ("isbn", "title", "author", "publisher", "category", "price",
                    "stock", "rating", "tags", "publish_date", "borrow_count"):
            value = book.get(key)
            if key == "publish_date":
                value = fmt_dt(value)
            print("  %-12s %s" % (key, value))

    # ------------------------------------------------------------------
    # 3/4. 排行榜
    # ------------------------------------------------------------------
    def menu_top_rated(self):
        n = ask("取前几名", "5")
        rows = self.books.top_rated(int(n) if str(n).isdigit() else 5)
        print("\n[评分排行榜]")
        for index, row in enumerate(rows, 1):
            print("  %2d. %-30s 评分 %.1f  借阅 %d 次"
                  % (index, row.get("title"), row.get("rating", 0),
                     row.get("borrow_count", 0)))

    def menu_top_borrowed(self):
        n = ask("取前几名", "5")
        self.stats.hot_books(int(n) if str(n).isdigit() else 5)

    # ------------------------------------------------------------------
    # 5. 新增图书
    # ------------------------------------------------------------------
    def menu_add_book(self):
        print("\n--- 新增图书 ---")
        isbn = ask("ISBN")
        if not isbn:
            print("[提示] ISBN 不能为空。")
            return
        if self.books.get_by_isbn(isbn):
            print("[提示] 该 ISBN 已存在，不能重复录入（唯一索引会拒绝）。")
            return
        title = ask("书名")
        author = ask("作者")
        publisher = ask("出版社")
        category = ask("类别")
        price = ask_float("价格", "0")
        stock = ask("库存", "0")
        rating = ask_float("评分（0—5）", "0")
        publish_date = ask("出版日期（YYYY-MM-DD，可空）")
        tags_text = ask("标签（多个用逗号分隔）")
        tags = [item.strip() for item in (tags_text or "").split(",") if item.strip()]
        self.books.add_book(
            isbn=isbn, title=title or "未命名", author=author or "未知",
            publisher=publisher or "未知", category=category or "未分类",
            price=price or 0, stock=int(stock) if str(stock).isdigit() else 0,
            rating=rating or 0, tags=tags, publish_date=publish_date,
        )
        print("[当前总数] books 共 %d 条" % self.books.total())

    # ------------------------------------------------------------------
    # 6/7/8. 更新与删除
    # ------------------------------------------------------------------
    def menu_update_stock(self):
        isbn = ask("图书 ISBN")
        delta = ask("库存变化量（正数入库，负数出库）", "-1")
        try:
            self.books.update_stock(isbn, int(delta))
        except ValueError:
            print("[提示] 变化量必须是整数。")

    def menu_discount(self):
        category = ask("类别")
        rate = ask_float("折扣系数（0.9 表示 9 折）", "0.9")
        if rate is None:
            return
        self.books.discount_category(category, rate)

    def menu_delete_book(self):
        isbn = ask("要删除的图书 ISBN")
        book = self.books.get_by_isbn(isbn)
        if not book:
            print("[提示] 没有找到该图书。")
            return
        confirm = ask("确认删除《%s》？(y/N)" % book.get("title"), "N")
        if str(confirm).lower() != "y":
            print("[已取消]")
            return
        self.books.delete(isbn)

    # ------------------------------------------------------------------
    # 9/10. 读者
    # ------------------------------------------------------------------
    def menu_search_readers(self):
        print("\n--- 读者查询 ---")
        keyword = ask("姓名/证号/邮箱关键词")
        college = ask("学院")
        level = ask("等级（普通/高级/教师）")
        rows = self.readers.search(keyword or None, college or None, level or None)
        print_readers(rows)

    def menu_reader_stats(self):
        print("\n--- 读者统计 ---")
        print("学院人数：")
        for row in self.readers.college_stats():
            print("  %-16s %d 人" % (row["_id"], row["reader_count"]))
        print("等级分布：")
        for row in self.readers.level_distribution():
            print("  %-8s %d 人" % (row["_id"], row["reader_count"]))
        print("学院清单（distinct）：%s" % "、".join(self.readers.distinct_colleges()))
        print("没有邮箱的读者：%d 人" % len(self.readers.without_email()))

    # ------------------------------------------------------------------
    # 11/12/13. 借阅
    # ------------------------------------------------------------------
    def menu_borrow(self):
        print("\n--- 借阅登记 ---")
        card_no = ask("借阅证号")
        isbn = ask("图书 ISBN")
        self.borrows.borrow(card_no, isbn)

    def menu_return(self):
        print("\n--- 归还处理 ---")
        card_no = ask("借阅证号")
        isbn = ask("图书 ISBN")
        self.borrows.return_book(card_no, isbn)

    def menu_overdue(self):
        days = ask("借阅超过多少天视为逾期", "30")
        rows = self.borrows.overdue(int(days) if str(days).isdigit() else 30)
        print("\n[逾期记录]")
        if not rows:
            print("[提示] 当前没有逾期记录。")
            return
        for log, overdue_days in rows:
            print("  %-12s %-15s %-6s 借阅 %s，逾期 %d 天"
                  % (log.get("reader_card"), log.get("book_isbn"),
                     log.get("status"), fmt_dt(log.get("borrow_date")), overdue_days))
        print("共 %d 条" % len(rows))

    # ------------------------------------------------------------------
    # 14/15/16/17. 统计
    # ------------------------------------------------------------------
    def menu_category_report(self):
        self.stats.category_report()

    def menu_trend(self):
        self.stats.borrow_trend()

    def menu_rankings(self):
        print("\n--- 活跃读者榜 ---")
        for row in self.stats.active_readers():
            print("  %-12s %-8s %-16s %d 次"
                  % (row["card_no"], row["name"], row["college"], row["borrow_times"]))
        print("\n--- 学院借阅排行 ---")
        for row in self.stats.college_ranking():
            print("  %-16s %d 次" % (row["college"], row["borrow_times"]))

    def menu_merge_stats(self):
        self.stats.merge_category_stats()
        self.stats.show_category_stats()

    def menu_borrow_summary(self):
        print("\n--- 借阅状态汇总 ---")
        for row in self.borrows.status_summary():
            print("  %-8s %d 条" % (row["_id"], row["count"]))
        print("\n--- 最近 10 条借阅流水 ---")
        print_logs(self.borrows.logs.find().sort("borrow_date", -1).limit(10))

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    def run(self):
        actions = {
            "1": self.menu_search_books,
            "2": self.menu_find_isbn,
            "3": self.menu_top_rated,
            "4": self.menu_top_borrowed,
            "5": self.menu_add_book,
            "6": self.menu_update_stock,
            "7": self.menu_discount,
            "8": self.menu_delete_book,
            "9": self.menu_search_readers,
            "10": self.menu_reader_stats,
            "11": self.menu_borrow,
            "12": self.menu_return,
            "13": self.menu_overdue,
            "14": self.menu_category_report,
            "15": self.menu_trend,
            "16": self.menu_rankings,
            "17": self.menu_merge_stats,
            "18": self.menu_borrow_summary,
        }
        while True:
            print(MENU)
            try:
                choice = input("请选择功能编号（0 退出）：").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[退出] 已取消输入。")
                break
            if choice in ("0", "q", "Q", "exit", "quit"):
                print("\n[退出] 正在关闭数据库连接 ...")
                break
            action = actions.get(choice)
            if not action:
                print("[提示] 无效的编号，请输入 0—18 之间的数字。")
                continue
            try:
                action()
            except (EOFError, KeyboardInterrupt):
                print("\n[取消] 已返回主菜单。")
            except PyMongoError as exc:
                print("\n[数据库错误] %s" % exc)
            except ValueError as exc:
                print("\n[输入错误] %s" % exc)
            except Exception as exc:  # 避免单个功能异常导致整个程序退出
                print("\n[运行错误] %s: %s" % (type(exc).__name__, exc))


def main():
    print("=" * 64)
    print("  图书情报检索与统计平台 · PyMongo 命令行程序")
    print("=" * 64)
    print("[连接配置] %s" % build_uri())
    ok, message = ping()
    print("[连接状态] %s" % message)
    if not ok:
        print("[提示] 请先启动 MongoDB 服务，或检查 mongodb_connect.py 中的连接参数。")
        close()
        sys.exit(1)

    db = get_db()
    show_counts(db)
    app = Application()
    try:
        app.run()
    finally:
        close()
        print("[完成] 数据库连接已关闭，程序结束。")


if __name__ == "__main__":
    main()
