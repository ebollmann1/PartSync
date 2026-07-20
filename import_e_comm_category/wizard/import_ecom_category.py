from odoo import models, fields, api
import base64
import tempfile
import pandas as pd
from io import BytesIO
from openpyxl import load_workbook
from odoo.exceptions import UserError
from psycopg2.extras import execute_values, Json

class ImportEcomCategories(models.TransientModel):
    _name = 'import.ecom.categories'
    _description = 'Import eCommerce Categories'

    file = fields.Binary(required=True, string="XLSX File")
    filename = fields.Char()

    def action_import(self):

        file_content = base64.b64decode(self.file)
        workbook = load_workbook(BytesIO(file_content), read_only=True)
        sheet = workbook.worksheets[0]

        headers = [h.value for h in sheet[1]]
        col = {name: i for i, name in enumerate(headers)}
        rows = sheet.iter_rows(min_row=2, values_only=True)

        Category = self.env['product.public.category']
        Category_rec = self.env['product.public.category'].search([])
        cr = self.env.cr
        lang = self.env.lang

        def norm(v):
            if not v:
                return ""
            return str(v).strip()

        # ------------------------------------------
        # LOAD EXISTING (ONE TIME FUNCTION)
        # ------------------------------------------
        def load_existing():
            cr.execute("SELECT id, name, parent_id FROM product_public_category")
            ex = {}
            for cid, name_json, parent in cr.fetchall():
                if isinstance(name_json, dict):
                    n = name_json.get(lang) or next(iter(name_json.values()))
                else:
                    n = name_json
                ex[(n.strip(), parent)] = cid
            return ex

        # ------------------------------------------
        # BULK INSERT
        # ------------------------------------------
        def bulk_sql_insert(items):
            if not items:
                return

            q = """
                INSERT INTO product_public_category (name, parent_id, position, create_uid, create_date)
                VALUES %s
                RETURNING id, name, parent_id
            """

            data = [
                (Json({lang: it['name']}), it['parent_id'], it['position'], self.env.uid, fields.Datetime.now())
                for it in items
            ]
            print("data===========",data)

            execute_values(cr, q, data)

        # ------------------------------------------
        # PASS 1 – COLLECT LEVEL DATA
        # ------------------------------------------
        lvl1 = {}  # name → position
        lvl2 = {}  # (sub_name, cat_name)
        lvl3 = {}  # (part_name, sub_name)
        leaves = []  # leaves rows

        count_lvl1 = 0
        count_lvl2 = 0
        count_lvl3 = 0
        count_leaf = 0

        for row in rows:
            cat_name = norm(row[col['categoryname']])
            sub_name = norm(row[col['SubCategoryName']])
            part_name = norm(row[col['PartTerminologyName']])
            pos_name = norm(row[col['Position']])

            cat_id = row[col['CategoryID']]
            sub_id = row[col['SubCategoryID']]
            part_id = row[col['PartTerminologyID']]
            pos_id = row[col['PositionID']]
            code_master = row[col['CodeMasterID']]

            if cat_name:
                lvl1.setdefault(cat_name, cat_id)

            if sub_name and cat_name:
                lvl2.setdefault((sub_name, cat_name), sub_id)

            if part_name and sub_name:
                lvl3.setdefault((part_name, sub_name, cat_name), part_id)

            if pos_name:
                leaves.append({
                    'name': pos_name,
                    'position': pos_id,
                    'cat': cat_name,
                    'sub': sub_name,
                    'part': part_name,
                    'code_master': code_master,
                    'category': cat_id,
                    'subcategory': sub_id,
                    'partterminology': part_id
                })

        # ------------------------------------------
        # PASS 2 – INSERT LEVEL 1
        # ------------------------------------------
        existing = load_existing()
        print("\n\n\n=====existing=======",existing)

        lvl1_insert = []
        for name, pos in lvl1.items():
            if (name, None) not in existing:
                lvl1_insert.append({'name': name, 'parent_id': None, 'position': pos})

        count_lvl1 += len(lvl1_insert)

        bulk_sql_insert(lvl1_insert)
        existing = load_existing()  # MUST REFRESH
        print("\n\n\n===after insert level 1==existing=======",existing)


        # ------------------------------------------
        # PASS 3 – INSERT LEVEL 2
        # ------------------------------------------
        lvl2_insert = []
        for (sub, cat), pos in lvl2.items():
            parent_id = existing.get((cat, None))
            print("\n\n\n===============parent_id",parent_id)
            if (sub, parent_id) not in existing:
                lvl2_insert.append({'name': sub, 'parent_id': parent_id, 'position': pos})

        count_lvl2 += len(lvl2_insert)
        bulk_sql_insert(lvl2_insert)
        existing = load_existing()
        print("\n\n\n===after insert level 2==existing=======",existing)

        # ------------------------------------------
        # PASS 4 – INSERT LEVEL 3
        # ------------------------------------------
        lvl3_insert = []
        for (part, sub, cat), pos in lvl3.items():
            # correct parent: sub belongs to cat
            cat_id = existing.get((cat, None))
            sub_id = existing.get((sub, cat_id))

            if sub_id and (part, sub_id) not in existing:
                lvl3_insert.append({'name': part, 'parent_id': sub_id, 'position': pos})

        count_lvl3 += len(lvl3_insert)
        bulk_sql_insert(lvl3_insert)
        existing = load_existing()
        print("\n\n\n===after insert level 3==existing=======", existing)

        # ------------------------------------------
        # PASS 5 – INSERT LEAVES
        # ------------------------------------------
        leaf_batch = []
        for lf in leaves:
            cat_id = existing.get((lf['cat'], None))
            sub_id = existing.get((lf['sub'], cat_id))
            part_id = existing.get((lf['part'], sub_id))

            leaf = {
                'name': lf['name'],
                'parent_id': part_id,
                'code_master': lf['code_master'],
                'category': lf['category'],
                'subcategory': lf['subcategory'],
                'partterminology': lf['partterminology'],
                'position': lf['position'],
            }
            print("=========leaf=========",leaf)
            leaf_batch.append(leaf)
        count_leaf += len(leaf_batch)
        print("\n +++++++++ len (leaf_batch) +++++", len(leaf_batch))
        for it in leaf_batch:
            cr.execute(
                """
                INSERT INTO product_public_category 
                (name, parent_id, code_master, category, subcategory, partterminology, position, create_uid, create_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    Json({lang: it['name']}),
                    it['parent_id'],
                    it['code_master'],
                    it['category'],
                    it['subcategory'],
                    it['partterminology'],
                    it['position'],
                    self.env.uid,
                    fields.Datetime.now()
                )
            )
        # Category.create(leaf_batch)

        def fix_parent_path():
            cr.execute("SELECT id, parent_id FROM product_public_category ORDER BY id")
            rows = cr.fetchall()

            parent_map = {}
            for cid, pid in rows:
                parent_map[cid] = pid

            def build_path(cat_id):
                path_ids = [cat_id]
                while parent_map.get(cat_id):
                    cat_id = parent_map[cat_id]
                    path_ids.append(cat_id)
                return "/".join(str(x) for x in reversed(path_ids)) + "/"

            update_vals = []
            for cid in parent_map:
                pp = build_path(cid)
                update_vals.append((pp, cid))

            query = """
                UPDATE product_public_category
                SET parent_path = data.parent_path
                FROM (VALUES %s) AS data(parent_path, id)
                WHERE product_public_category.id = data.id;
            """
            execute_values(cr, query, update_vals)

        # Call the function
        fix_parent_path()

        # Now let Odoo recompute display name
        Category_rec._compute_parents_and_self()
        Category_rec._compute_display_name()

        total_created = count_lvl1 + count_lvl2 + count_lvl3 + count_leaf

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Completed',
                'message': (
                    f'Categories Created Successfully!\n'
                    f'Total Created: {total_created}'
                ),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }