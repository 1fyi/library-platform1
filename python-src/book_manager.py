# -*- coding: utf-8 -*-
"""
book_manager.py —— 图书管理模块（任务五 ST-5.3）

封装图书的增、删、改、查与排行榜：
    insert_one / insert_many / find / find_one / update_one /
    delete_one / delete_many

对应任务书中的：
    F5 精确与范围检索、F6 组合条件检索、F7 排序与分页、F9 热门排行
    U1 库存减少、U2 类别打折、U3 新增字段并记录时间、U4 删除 tags 字段
"""

from pymongo import ASCENDING, DESCENDING

from mongodb_connect import (
    COLL_BOOKS,
    fmt_dt,
    get_db,
    now,
    parse_date,
)


def print_books(rows, limit=20):
    """以表格形式打印图书列表；rows 可以是游标或列表。"""
    rows = list(rows)
    if not rows:
        print("[提示] 没有查询到符合条件的图书。")
        return 0
    print("-" * 104)
    print("%-15s %-28s %-14s %-6s %-5s %-5s %-12s" %
          ("ISBN", "书名", "作者", "类别", "价格", "库存", "出版日期"))
    print("-" * 104)
    for book in rows[:limit]:
        print("%-15s %-28s %-14s %-6s %-5.2f %-5s %-12s" % (
            book.get("isbn", "-"),
            str(book.get("title", "-"))[:26],
            str(book.get("author", "-"))[:12],
            book.get("category", "-"),
            float(book.get("price", 0)),
            book.get("stock", 0),
            fmt_dt(book.get("publish_date")),
        ))
    print("-" * 104)
    print("共 %d 条记录%s" % (len(rows), "（只显示前 %d 条）" % limit if len(rows) > limit else ""))
    return len(rows)


class BookManager:
    """图书集合 books 的操作封装。"""

    def __init__(self, db=None):
        self.db = db if db is not None else get_db()
        self.col = self.db[COLL_BOOKS]
        self.logs = self.db["book_logs"]

    # ------------------------------------------------------------------
    # 一、新增
    # ------------------------------------------------------------------
    def total(self):
        """图书总数。"""
        return self.col.count_documents({})

    def add_book(self, isbn, title, author, publisher, category,
                 price, stock, rating, tags=None, publish_date=None,
                 borrow_count=0):
        """新增一本图书（insert_one），返回 InsertOneResult。"""
        doc = {
            "isbn": str(isbn).strip(),
            "title": title.strip(),
            "author": author.strip(),
            "publisher": publisher.strip(),
            "category": category.strip(),
            "price": float(price),
            "stock": int(stock),
            "rating": float(rating),
            "tags": tags or [],
            "publish_date": parse_date(publish_date) or now(),
            "borrow_count": int(borrow_count),
        }
        result = self.col.insert_one(doc)
        print("[新增成功] 《%s》 _id = %s" % (doc["title"], result.inserted_id))
        # 固定集合 book_logs 记录一条操作日志（时间序列/固定集合演示）
        try:
            self.logs.insert_one({"action": "insert", "isbn": doc["isbn"], "time": now()})
        except Exception:
            pass
        return result

    def add_books(self, books):
        """批量新增（insert_many），books 为文档列表。"""
        if not books:
            print("[提示] 没有需要新增的数据。")
            return None
        result = self.col.insert_many(books)
        print("[批量新增成功] 共插入 %d 条文档" % len(result.inserted_ids))
        return result

    # ------------------------------------------------------------------
    # 二、查询
    # ------------------------------------------------------------------
    def get_by_isbn(self, isbn):
        """按 ISBN 精确查找（find_one）。"""
        return self.col.find_one({"isbn": str(isbn).strip()})

    def search(self, keyword=None, category=None, price_min=None,
               price_max=None, rating_min=None, tags=None, limit=0):
        """
        组合条件检索：
            keyword    书名/作者模糊匹配（$regex）
            category   类别精确匹配
            price_min  最低价格（$gte）
            price_max  最高价格（$lte）
            rating_min 最低评分（$gte）
            tags       标签列表，要求全部包含（$all，多键匹配）
            limit      取前 N 条（0 表示不限制）
        """
        conditions = []
        if keyword:
            regex = {"$regex": keyword, "$options": "i"}
            conditions.append({"$or": [{"title": regex}, {"author": regex},
                                       {"publisher": regex}]})
        if category:
            conditions.append({"category": category})
        if price_min is not None or price_max is not None:
            price = {}
            if price_min is not None:
                price["$gte"] = float(price_min)
            if price_max is not None:
                price["$lte"] = float(price_max)
            conditions.append({"price": price})
        if rating_min is not None:
            conditions.append({"rating": {"$gte": float(rating_min)}})
        if tags:
            conditions.append({"tags": {"$all": list(tags)}})

        query = {"$and": conditions} if conditions else {}
        cursor = self.col.find(query)
        if limit:
            cursor = cursor.limit(int(limit))
        return list(cursor)

    def search_by_price_range(self, low, high):
        """按价格区间检索。"""
        return list(self.col.find({"price": {"$gte": float(low), "$lte": float(high)}}))

    def top_rated(self, n=5):
        """评分降序取前 N 本（sort + limit + 投影）。"""
        return list(self.col.find(
            {},
            {"_id": 0, "isbn": 1, "title": 1, "rating": 1, "borrow_count": 1},
        ).sort([("rating", DESCENDING), ("borrow_count", DESCENDING)]).limit(int(n)))

    def top_borrowed(self, n=5):
        """按累计借阅次数降序取前 N 本（热门排行）。"""
        return list(self.col.find(
            {},
            {"_id": 0, "isbn": 1, "title": 1, "borrow_count": 1},
        ).sort("borrow_count", DESCENDING).limit(int(n)))

    def distinct_categories(self):
        """获取所有图书类别（distinct）。"""
        return sorted(self.col.distinct("category"))

    def list_all(self, limit=20):
        """列出图书。"""
        return list(self.col.find().sort("isbn", ASCENDING).limit(int(limit)))

    def count_by_category(self):
        """按类别统计数量（聚合）。"""
        return list(self.col.aggregate([
            {"$group": {"_id": "$category", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]))

    # ------------------------------------------------------------------
    # 三、更新
    # ------------------------------------------------------------------
    def update_stock(self, isbn, delta):
        """库存增减（update_one + $inc），库存不足时不允许扣减。"""
        book = self.get_by_isbn(isbn)
        if not book:
            print("[提示] 未找到 ISBN 为 %s 的图书。" % isbn)
            return 0
        new_stock = int(book.get("stock", 0)) + int(delta)
        if new_stock < 0:
            print("[提示] 库存不足：当前库存 %d，无法减少 %d 本。"
                  % (book.get("stock", 0), abs(int(delta))))
            return 0
        result = self.col.update_one(
            {"isbn": str(isbn).strip()},
            {"$inc": {"stock": int(delta)}},
        )
        print("[更新完成] 《%s》库存 %d -> %d，受影响文档数 %d"
              % (book.get("title"), book.get("stock", 0), new_stock,
                 result.modified_count))
        return result.modified_count

    def discount_category(self, category, rate=0.9):
        """某类别图书统一打折（updateMany + $mul）。"""
        result = self.col.update_many(
            {"category": category},
            {"$mul": {"price": float(rate)}},
        )
        print("[更新完成] 类别「%s」共匹配 %d 条，实际修改 %d 条（%.1f 折）"
              % (category, result.matched_count, result.modified_count, float(rate) * 10))
        return result.modified_count

    def touch(self, isbn):
        """为图书新增 last_update 字段并写入服务器当前时间（$currentDate）。"""
        result = self.col.update_one(
            {"isbn": str(isbn).strip()},
            {"$currentDate": {"last_update": True}},
        )
        print("[更新完成] ISBN %s 增加 last_update 字段，受影响文档数 %d"
              % (isbn, result.modified_count))
        return result.modified_count

    def remove_tags(self, isbn):
        """删除某本图书的 tags 字段（$unset）。"""
        result = self.col.update_one(
            {"isbn": str(isbn).strip()},
            {"$unset": {"tags": ""}},
        )
        print("[更新完成] ISBN %s 的 tags 字段已删除，受影响文档数 %d"
              % (isbn, result.modified_count))
        return result.modified_count

    # ------------------------------------------------------------------
    # 四、删除
    # ------------------------------------------------------------------
    def delete(self, isbn):
        """按 ISBN 删除一本图书（delete_one）。"""
        result = self.col.delete_one({"isbn": str(isbn).strip()})
        print("[删除完成] 删除 %d 条图书记录" % result.deleted_count)
        return result.deleted_count

    def delete_by_category(self, category):
        """按类别批量删除（delete_many）。"""
        result = self.col.delete_many({"category": category})
        print("[删除完成] 类别「%s」共删除 %d 条图书记录"
              % (category, result.deleted_count))
        return result.deleted_count
