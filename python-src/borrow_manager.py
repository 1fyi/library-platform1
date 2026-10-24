# -*- coding: utf-8 -*-
"""
borrow_manager.py —— 借阅管理模块（任务五 ST-5.3）

封装借阅登记、归还处理、逾期查询与借阅流水检索：
    insert_one / find / update_one / delete_one / delete_many

重要说明：
    borrow_logs 是“时间序列集合”。MongoDB 规定时间序列集合只能做
    批量更新/删除（且没有 metaField 时连更新都不允许），因此“归还”
    采用“删除原借出记录 + 插入一条已归还记录”的方式实现，
    这与直接修改 status / return_date 的业务效果一致。
"""

from pymongo import DESCENDING

from mongodb_connect import (
    COLL_BOOKS,
    COLL_BORROW_LOGS,
    COLL_READERS,
    fmt_dt,
    get_db,
    now,
)


def print_logs(rows, limit=30):
    """打印借阅流水。"""
    rows = list(rows)
    if not rows:
        print("[提示] 没有查询到借阅记录。")
        return 0
    print("-" * 96)
    print("%-12s %-15s %-10s %-20s %-20s" %
          ("借阅证号", "图书 ISBN", "状态", "借阅时间", "归还时间"))
    print("-" * 96)
    for log in rows[:limit]:
        print("%-12s %-15s %-10s %-20s %-20s" % (
            log.get("reader_card", "-"),
            log.get("book_isbn", "-"),
            log.get("status", "-"),
            fmt_dt(log.get("borrow_date"), "%Y-%m-%d %H:%M"),
            fmt_dt(log.get("return_date"), "%Y-%m-%d %H:%M"),
        ))
    print("-" * 96)
    print("共 %d 条记录%s" % (len(rows), "（只显示前 %d 条）" % limit if len(rows) > limit else ""))
    return len(rows)


class BorrowManager:
    """借阅流水集合 borrow_logs 的操作封装。"""

    def __init__(self, db=None):
        self.db = db if db is not None else get_db()
        self.logs = self.db[COLL_BORROW_LOGS]
        self.books = self.db[COLL_BOOKS]
        self.readers = self.db[COLL_READERS]

    def total(self):
        return self.logs.count_documents({})

    # ------------------------------------------------------------------
    # 一、借阅登记
    # ------------------------------------------------------------------
    def borrow(self, card_no, isbn):
        """借书：写一条“借出”流水，同时库存 -1、累计借阅次数 +1。"""
        card_no = str(card_no).strip()
        isbn = str(isbn).strip()

        reader = self.readers.find_one({"card_no": card_no})
        if not reader:
            print("[提示] 不存在借阅证号 %s 的读者。" % card_no)
            return 0
        book = self.books.find_one({"isbn": isbn})
        if not book:
            print("[提示] 不存在 ISBN 为 %s 的图书。" % isbn)
            return 0
        if int(book.get("stock", 0)) <= 0:
            print("[提示] 《%s》库存为 0，无法借出。" % book.get("title"))
            return 0
        opened = self.logs.find_one({
            "reader_card": card_no,
            "book_isbn": isbn,
            "status": "借出",
        })
        if opened:
            print("[提示] 该读者已借出这本书且尚未归还，请勿重复借阅。")
            return 0

        log = {
            "borrow_date": now(),
            "reader_card": card_no,
            "book_isbn": isbn,
            "status": "借出",
        }
        inserted = self.logs.insert_one(log)
        updated = self.books.update_one(
            {"isbn": isbn},
            {"$inc": {"stock": -1, "borrow_count": 1}},
        )
        print("[借阅成功] %s（%s）借出《%s》，流水 _id = %s，库存更新 %d 条"
              % (reader.get("name"), card_no, book.get("title"),
                 inserted.inserted_id, updated.modified_count))
        return 1

    # ------------------------------------------------------------------
    # 二、归还处理
    # ------------------------------------------------------------------
    def return_book(self, card_no, isbn):
        """还书：把最近一条“借出”流水改为“已归还”，库存 +1。"""
        card_no = str(card_no).strip()
        isbn = str(isbn).strip()
        log = self.logs.find_one(
            {"reader_card": card_no, "book_isbn": isbn, "status": "借出"},
            sort=[("borrow_date", DESCENDING)],
        )
        if not log:
            print("[提示] 没有找到该读者对这本书的“借出”记录，无需归还。")
            return 0

        # 时间序列集合不支持单条更新，采用删除 + 重新插入等价实现
        deleted = self.logs.delete_one({"_id": log["_id"]})
        new_log = {
            "borrow_date": log["borrow_date"],
            "return_date": now(),
            "reader_card": card_no,
            "book_isbn": isbn,
            "status": "已归还",
        }
        inserted = self.logs.insert_one(new_log)
        # 用 update_many 更新库存：过滤条件带唯一 ISBN，实际只会影响 1 条
        updated = self.books.update_many({"isbn": isbn}, {"$inc": {"stock": 1}})
        print("[归还成功] 原借出流水已替换：删除 %d 条，新增 1 条（_id = %s），库存更新 %d 条"
              % (deleted.deleted_count, inserted.inserted_id, updated.modified_count))
        return 1

    # ------------------------------------------------------------------
    # 三、查询
    # ------------------------------------------------------------------
    def history_by_reader(self, card_no):
        """某位读者的借阅历史。"""
        return list(self.logs.find({"reader_card": str(card_no).strip()})
                    .sort("borrow_date", DESCENDING))

    def history_by_book(self, isbn):
        """某本图书的借阅历史。"""
        return list(self.logs.find({"book_isbn": str(isbn).strip()})
                    .sort("borrow_date", DESCENDING))

    def overdue(self, days=30):
        """
        逾期查询：
            1) 状态本身为“逾期”的记录；
            2) 状态为“借出”且借出时间超过 days 天的记录。
        返回 (记录列表, 每条记录逾期天数)。
        """
        from datetime import timedelta
        cutoff = now() - timedelta(days=int(days))
        query = {"$or": [
            {"status": "逾期"},
            {"status": "借出", "borrow_date": {"$lt": cutoff}},
        ]}
        rows = list(self.logs.find(query).sort("borrow_date", 1))
        result = []
        for row in rows:
            borrow_date = row.get("borrow_date")
            if borrow_date is None:
                continue
            if borrow_date.tzinfo is None:
                from datetime import timezone
                borrow_date = borrow_date.replace(tzinfo=timezone.utc)
            overdue_days = (now() - borrow_date).days - int(days)
            result.append((row, max(overdue_days, 0)))
        return result

    def status_summary(self):
        """各状态借阅记录数量（$group）。"""
        return list(self.logs.aggregate([
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]))

    # ------------------------------------------------------------------
    # 四、删除（D1 / D2）
    # ------------------------------------------------------------------
    def delete_returned_one(self, card_no, isbn):
        """删除一条已归还的借阅记录（delete_one + $eq）。"""
        result = self.logs.delete_one({
            "reader_card": str(card_no).strip(),
            "book_isbn": str(isbn).strip(),
            "status": "已归还",
        })
        print("[删除完成] 删除已归还记录 %d 条" % result.deleted_count)
        return result.deleted_count

    def delete_overdue(self):
        """清理所有逾期记录（delete_many）。"""
        result = self.logs.delete_many({"status": "逾期"})
        print("[删除完成] 清理逾期记录 %d 条" % result.deleted_count)
        return result.deleted_count
