# -*- coding: utf-8 -*-
"""
reader_manager.py —— 读者管理模块（任务五 ST-5.3）

封装读者信息管理、学院统计、等级分布：
    find / count_documents / distinct / replace_one
"""

from pymongo import DESCENDING

from mongodb_connect import COLL_READERS, fmt_dt, get_db, now, parse_date


def print_readers(rows, limit=20):
    """表格形式打印读者。"""
    rows = list(rows)
    if not rows:
        print("[提示] 没有查询到符合条件的读者。")
        return 0
    print("-" * 96)
    print("%-12s %-8s %-16s %-10s %-26s %-12s" %
          ("借阅证号", "姓名", "学院", "等级", "邮箱", "注册时间"))
    print("-" * 96)
    for reader in rows[:limit]:
        print("%-12s %-8s %-16s %-10s %-26s %-12s" % (
            reader.get("card_no", "-"),
            reader.get("name", "-"),
            reader.get("college", "-"),
            reader.get("level", "-"),
            reader.get("email") or "（空）",
            fmt_dt(reader.get("register_date")),
        ))
    print("-" * 96)
    print("共 %d 条记录%s" % (len(rows), "（只显示前 %d 条）" % limit if len(rows) > limit else ""))
    return len(rows)


class ReaderManager:
    """读者集合 readers 的操作封装。"""

    def __init__(self, db=None):
        self.db = db if db is not None else get_db()
        self.col = self.db[COLL_READERS]

    def total(self):
        return self.col.count_documents({})

    # ------------------------------------------------------------------
    # 一、新增
    # ------------------------------------------------------------------
    def add_reader(self, card_no, name, college, email=None, phone="",
                   level="普通", register_date=None, fav_categories=None):
        """新增读者（insert_one）。"""
        doc = {
            "card_no": str(card_no).strip(),
            "name": name.strip(),
            "college": college.strip(),
            "email": (email or "").strip() or None,
            "phone": phone.strip(),
            "level": level.strip(),
            "register_date": parse_date(register_date) or now(),
            "fav_categories": fav_categories or [],
        }
        result = self.col.insert_one(doc)
        print("[新增成功] 读者 %s（%s） _id = %s"
              % (doc["name"], doc["card_no"], result.inserted_id))
        return result

    # ------------------------------------------------------------------
    # 二、查询
    # ------------------------------------------------------------------
    def get_by_card(self, card_no):
        """按借阅证号精确查找（find_one）。"""
        return self.col.find_one({"card_no": str(card_no).strip()})

    def search(self, keyword=None, college=None, level=None):
        """按姓名/证号模糊、学院、等级组合查询。"""
        conditions = []
        if keyword:
            regex = {"$regex": keyword, "$options": "i"}
            conditions.append({"$or": [{"name": regex}, {"card_no": regex},
                                       {"email": regex}]})
        if college:
            conditions.append({"college": college})
        if level:
            conditions.append({"level": level})
        query = {"$and": conditions} if conditions else {}
        return list(self.col.find(query).sort("card_no", 1))

    def list_all(self, limit=20):
        return list(self.col.find().sort("card_no", 1).limit(int(limit)))

    def without_email(self):
        """查找 email 为空的读者（$eq: null）。"""
        return list(self.col.find({"email": None}))

    # ------------------------------------------------------------------
    # 三、统计
    # ------------------------------------------------------------------
    def college_stats(self):
        """按学院统计读者人数（$group）。"""
        return list(self.col.aggregate([
            {"$group": {"_id": "$college", "reader_count": {"$sum": 1}}},
            {"$sort": {"reader_count": DESCENDING, "_id": 1}},
        ]))

    def level_distribution(self):
        """借阅等级分布（$group）。"""
        return list(self.col.aggregate([
            {"$group": {"_id": "$level", "reader_count": {"$sum": 1}}},
            {"$sort": {"reader_count": DESCENDING}},
        ]))

    def distinct_colleges(self):
        """所有学院清单（distinct）。"""
        return sorted(self.col.distinct("college"))

    def distinct_levels(self):
        """所有借阅等级（distinct）。"""
        return sorted(self.col.distinct("level"))

    def count_by_level(self, level):
        """某一等级人数（count_documents）。"""
        return self.col.count_documents({"level": level})

    # ------------------------------------------------------------------
    # 四、替换（D3）
    # ------------------------------------------------------------------
    def replace_reader(self, card_no, new_doc):
        """
        整体替换一位读者的信息（replaceOne），保留 _id。
        new_doc 必须包含完整的字段，函数会自动补上 card_no。
        """
        new_doc = dict(new_doc)
        new_doc["card_no"] = str(card_no).strip()
        if not new_doc.get("register_date"):
            new_doc["register_date"] = now()
        result = self.col.replace_one({"card_no": str(card_no).strip()}, new_doc)
        print("[替换完成] 读者 %s 匹配 %d 条，修改 %d 条（_id 保持不变）"
              % (card_no, result.matched_count, result.modified_count))
        return result.modified_count
