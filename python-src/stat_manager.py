# -*- coding: utf-8 -*-
"""
stat_manager.py —— 统计分析模块（任务五 ST-5.3 / ST-5.4）

使用聚合管道完成分类统计、借阅趋势、畅销榜、活跃读者、学院排行，
并把分类统计结果写入 category_stats 集合。
对应任务书：A1—A9、F8—F12。
"""

from pymongo.errors import OperationFailure

from mongodb_connect import (
    COLL_BOOKS,
    COLL_BORROW_LOGS,
    COLL_CATEGORY_STATS,
    COLL_READERS,
    get_db,
)


def print_rows(title, rows, fields, headers=None):
    """通用表格打印：fields 为取值字段名，headers 为表头。"""
    rows = list(rows)
    print("\n== %s ==" % title)
    if not rows:
        print("[提示] 没有统计结果。")
        return 0
    headers = headers or fields
    widths = []
    for index, name in enumerate(headers):
        width = len(str(name))
        for row in rows:
            width = max(width, len(str(row.get(fields[index], ""))))
        widths.append(min(width, 28))
    line = "-" * (sum(widths) + 2 * len(widths))
    print(line)
    print("  ".join(str(name).ljust(widths[index]) for index, name in enumerate(headers)))
    print(line)
    for row in rows:
        cells = []
        for index, field in enumerate(fields):
            text = str(row.get(field, ""))
            if len(text) > widths[index]:
                text = text[:widths[index] - 1] + "…"
            cells.append(text.ljust(widths[index]))
        print("  ".join(cells))
    print(line)
    print("共 %d 条" % len(rows))
    return len(rows)


class StatManager:
    """统计分析封装。"""

    def __init__(self, db=None):
        self.db = db if db is not None else get_db()
        self.books = self.db[COLL_BOOKS]
        self.readers = self.db[COLL_READERS]
        self.logs = self.db[COLL_BORROW_LOGS]
        self.stats = self.db[COLL_CATEGORY_STATS]

    # ------------------------------------------------------------------
    # A1 分类统计（同时满足 ST-5.4 的库存总量、平均价格、图书数量）
    # ------------------------------------------------------------------
    def category_report(self, verbose=True):
        rows = list(self.books.aggregate([
            {"$group": {
                "_id": "$category",
                "book_count": {"$sum": 1},
                "avg_rating": {"$avg": "$rating"},
                "stock_total": {"$sum": "$stock"},
                "avg_price": {"$avg": "$price"},
                "max_stock": {"$max": "$stock"},
                "min_stock": {"$min": "$stock"},
            }},
            {"$sort": {"stock_total": -1, "_id": 1}},
        ]))
        for row in rows:
            row["category"] = row.pop("_id")
            row["avg_rating"] = round(row["avg_rating"], 2)
            row["avg_price"] = round(row["avg_price"], 2)
        if verbose:
            print_rows("A1 分类统计（按库存总量降序）", rows,
                       ["category", "book_count", "avg_rating", "stock_total",
                        "avg_price", "max_stock", "min_stock"],
                       ["类别", "图书数量", "平均评分", "库存总量", "平均价格",
                        "最高库存", "最低库存"])
        return rows

    # ------------------------------------------------------------------
    # A2 出版社图书数量 Top 5（$group + $topN）
    # ------------------------------------------------------------------
    def publisher_top(self, n=5, verbose=True):
        n = int(n)
        pipeline = [
            {"$group": {"_id": "$publisher", "count": {"$sum": 1}}},
            {"$group": {"_id": None, "top": {"$topN": {
                "n": n,
                "sortBy": {"count": -1, "_id": 1},
                "output": {"publisher": "$_id", "count": "$count"},
            }}}},
            {"$unwind": "$top"},
            {"$replaceRoot": {"newRoot": "$top"}},
        ]
        try:
            rows = list(self.books.aggregate(pipeline))
        except OperationFailure:
            # 兼容 MongoDB 5.2 以下版本：改用 $sort + $limit
            rows = list(self.books.aggregate([
                {"$group": {"_id": "$publisher", "count": {"$sum": 1}}},
                {"$sort": {"count": -1, "_id": 1}},
                {"$limit": n},
            ]))
            for row in rows:
                row["publisher"] = row.pop("_id")
        if verbose:
            print_rows("A2 出版社图书数量 Top %d" % n, rows,
                       ["publisher", "count"], ["出版社", "图书数量"])
        return rows

    # ------------------------------------------------------------------
    # A3 文档数最多的图书类别（$sortByCount）
    # ------------------------------------------------------------------
    def category_sort_by_count(self, verbose=True):
        rows = list(self.books.aggregate([{"$sortByCount": "$category"}]))
        for row in rows:
            row["category"] = row.pop("_id")
        if verbose:
            print_rows("A3 类别文档数排名", rows,
                       ["category", "count"], ["类别", "图书数量"])
        return rows

    # ------------------------------------------------------------------
    # A4 评分最高的 3 本图书（$sort + $limit + $project）
    # ------------------------------------------------------------------
    def top_rated_books(self, n=3, verbose=True):
        rows = list(self.books.aggregate([
            {"$sort": {"rating": -1, "borrow_count": -1}},
            {"$limit": int(n)},
            {"$project": {"_id": 0, "title": 1, "borrow_count": 1}},
        ]))
        if verbose:
            print_rows("A4 评分最高的 %d 本图书" % int(n), rows,
                       ["title", "borrow_count"], ["书名", "借阅次数"])
        return rows

    # ------------------------------------------------------------------
    # A5 销售额 = 单价 × 借阅次数，保留两位小数
    # ------------------------------------------------------------------
    def sales_report(self, limit=10, verbose=True):
        rows = list(self.books.aggregate([
            {"$project": {
                "_id": 0,
                "title": 1,
                "price": 1,
                "borrow_count": 1,
                "sales": {"$round": [{"$multiply": ["$price", "$borrow_count"]}, 2]},
            }},
            {"$sort": {"sales": -1}},
            {"$limit": int(limit)},
        ]))
        if verbose:
            print_rows("A5 图书销售额（单价 x 借阅次数）Top %d" % int(limit), rows,
                       ["title", "price", "borrow_count", "sales"],
                       ["书名", "单价", "借阅次数", "销售额"])
        return rows

    # ------------------------------------------------------------------
    # A6 按借阅年份统计借阅量，输出 “2024年” 格式
    # ------------------------------------------------------------------
    def borrow_trend(self, verbose=True):
        rows = list(self.logs.aggregate([
            {"$group": {
                "_id": {"$year": {"date": "$borrow_date", "timezone": "+08:00"}},
                "count": {"$sum": 1},
            }},
            {"$project": {
                "_id": 0,
                "year": "$_id",
                "label": {"$dateToString": {
                    "format": "%Y年",
                    "date": {"$dateFromParts": {"year": "$_id"}},
                }},
                "count": 1,
            }},
            {"$sort": {"year": 1}},
        ]))
        if verbose:
            print_rows("A6 借阅趋势（按年份）", rows,
                       ["label", "count"], ["年份", "借阅量"])
        return rows

    # ------------------------------------------------------------------
    # A7 借阅最多的前 5 名读者（$group + $sort + $limit + $lookup）
    # ------------------------------------------------------------------
    def active_readers(self, n=5, verbose=True):
        rows = list(self.logs.aggregate([
            {"$group": {"_id": "$reader_card", "borrow_times": {"$sum": 1}}},
            {"$sort": {"borrow_times": -1, "_id": 1}},
            {"$limit": int(n)},
            {"$lookup": {"from": COLL_READERS, "localField": "_id",
                         "foreignField": "card_no", "as": "reader"}},
            {"$unwind": {"path": "$reader", "preserveNullAndEmptyArrays": True}},
            {"$project": {
                "_id": 0,
                "card_no": "$_id",
                "name": {"$ifNull": ["$reader.name", "（读者已删除）"]},
                "college": {"$ifNull": ["$reader.college", "-"]},
                "borrow_times": 1,
            }},
        ]))
        if verbose:
            print_rows("A7 活跃读者 Top %d" % int(n), rows,
                       ["card_no", "name", "college", "borrow_times"],
                       ["借阅证号", "姓名", "学院", "借阅次数"])
        return rows

    # ------------------------------------------------------------------
    # A8 学院借阅量排行榜（$lookup）
    # ------------------------------------------------------------------
    def college_ranking(self, verbose=True):
        rows = list(self.logs.aggregate([
            {"$lookup": {"from": COLL_READERS, "localField": "reader_card",
                         "foreignField": "card_no", "as": "reader"}},
            {"$unwind": "$reader"},
            {"$group": {"_id": "$reader.college", "borrow_times": {"$sum": 1}}},
            {"$sort": {"borrow_times": -1, "_id": 1}},
            {"$project": {"_id": 0, "college": "$_id", "borrow_times": 1}},
        ]))
        if verbose:
            print_rows("A8 学院借阅量排行榜", rows,
                       ["college", "borrow_times"], ["学院", "借阅量"])
        return rows

    # ------------------------------------------------------------------
    # A9 分类统计结果落库（$merge）
    # ------------------------------------------------------------------
    def merge_category_stats(self):
        pipeline = [
            {"$group": {
                "_id": "$category",
                "book_count": {"$sum": 1},
                "avg_rating": {"$avg": "$rating"},
                "stock_total": {"$sum": "$stock"},
                "avg_price": {"$avg": "$price"},
                "max_stock": {"$max": "$stock"},
                "min_stock": {"$min": "$stock"},
            }},
            {"$merge": {
                "into": COLL_CATEGORY_STATS,
                "on": "_id",
                "whenMatched": "replace",
                "whenNotMatched": "insert",
            }},
        ]
        # $merge 是写阶段，必须把游标消费完才会真正执行
        list(self.books.aggregate(pipeline))
        count = self.stats.count_documents({})
        print("[落库完成] category_stats 现有 %d 条分类统计结果" % count)
        return count

    def show_category_stats(self, verbose=True):
        rows = list(self.stats.find({}).sort("_id", 1))
        if verbose:
            print_rows("category_stats 集合内容", rows,
                       ["_id", "book_count", "avg_rating", "stock_total",
                        "avg_price", "max_stock", "min_stock"],
                       ["类别", "数量", "平均评分", "库存总量", "平均价格",
                        "最高库存", "最低库存"])
        return rows

    # ------------------------------------------------------------------
    # 热门图书（F9）
    # ------------------------------------------------------------------
    def hot_books(self, n=5, verbose=True):
        rows = list(self.books.aggregate([
            {"$sort": {"borrow_count": -1, "_id": 1}},
            {"$limit": int(n)},
            {"$project": {"_id": 0, "title": 1, "borrow_count": 1}},
        ]))
        if verbose:
            print_rows("热门图书 Top %d" % int(n), rows,
                       ["title", "borrow_count"], ["书名", "累计借阅次数"])
        return rows

    # ------------------------------------------------------------------
    # 视图统计（任务六验收用）
    # ------------------------------------------------------------------
    def in_stock_count(self):
        return self.db["book_in_stock"].count_documents({})
