# -*- coding: utf-8 -*-

from odoo import api, fields, models

import logging
_logger = logging.getLogger(__name__)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    fitment_make_ids = fields.Many2many(
        'fitment.make',
        relation='product_product_fitment_make_rel',
        column1='product_id',
        column2='make_id',
        compute="_compute_fitment_filters",
        store=True,
    )

    fitment_model_ids = fields.Many2many(
        'fitment.model',
        relation='product_product_fitment_model_rel',
        column1='product_id',
        column2='model_id',
        compute="_compute_fitment_filters",
        store=True,
    )

    fitment_year_ids = fields.Many2many(
        'fitment.year',
        relation='product_product_fitment_year_rel',
        column1='product_id',
        column2='year_id',
        compute="_compute_fitment_filters",
        store=True,
    )

    fitment_submodel_ids = fields.Many2many(
        'fitment.submodel',
        relation='product_product_fitment_submodel_rel',
        column1='product_id',
        column2='submodel_id',
        compute="_compute_fitment_filters",
        store=True,
    )

    fitment_wheel_ids = fields.Many2many(
        'fitment.rear.wheels',
        relation='product_product_fitment_wheel_rel',
        column1='product_id',
        column2='wheel_id',
        compute="_compute_fitment_filters",
        store=True,
    )

    fitment_vehicle_platform_ids = fields.Many2many(
        'vehicle.platform',
        relation='product_product_fitment_platform_rel',
        column1='product_id',
        column2='platform_id',
        compute="_compute_fitment_filters",
        store=True,
    )

    @api.depends(
        'customer_product_master_ids.fitment_ids.make_id',
        'customer_product_master_ids.fitment_ids.model_id',
        'customer_product_master_ids.fitment_ids.year_id',
        'customer_product_master_ids.fitment_ids.submodel_id',
        'customer_product_master_ids.fitment_ids.rear_wheels_id',
        'customer_product_master_ids.fitment_ids.vehicle_platform_id',
    )
    def _compute_fitment_filters(self):
        for product in self:
            fitments = product.customer_product_master_ids.mapped('fitment_ids')
            product.fitment_make_ids = fitments.mapped('make_id')
            product.fitment_model_ids = fitments.mapped('model_id')
            product.fitment_year_ids = fitments.mapped('year_id')
            product.fitment_submodel_ids = fitments.mapped('submodel_id')
            product.fitment_wheel_ids = fitments.mapped('rear_wheels_id')
            product.fitment_vehicle_platform_ids = fitments.mapped('vehicle_platform_id')

    # ── Field → (relation_table, comodel_col, comodel_table) ─────────────
    _FITMENT_FIELD_CONFIG = {
        'fitment_make_ids':             ('product_product_fitment_make_rel',     'make_id',     'fitment_make'),
        'fitment_model_ids':            ('product_product_fitment_model_rel',    'model_id',    'fitment_model'),
        'fitment_year_ids':             ('product_product_fitment_year_rel',     'year_id',     'fitment_year'),
        'fitment_submodel_ids':         ('product_product_fitment_submodel_rel', 'submodel_id', 'fitment_submodel'),
        'fitment_wheel_ids':            ('product_product_fitment_wheel_rel',    'wheel_id',    'fitment_rear_wheels'),
        'fitment_vehicle_platform_ids': ('product_product_fitment_platform_rel', 'platform_id', 'vehicle_platform'),
    }
    @api.model
    def search_panel_select_multi_range(self, field_name, **kwargs):
        if field_name not in self._FITMENT_FIELD_CONFIG:
            return super().search_panel_select_multi_range(field_name, **kwargs)

        rel_table, comodel_col, comodel_table = self._FITMENT_FIELD_CONFIG[field_name]

        filter_domain = kwargs.get('filter_domain', [])
        search_domain = kwargs.get('search_domain', [])

        try:
            # ── Step 1: Extract selected values for fitment fields from domains ────
            field_to_col = {
                'fitment_make_ids': 'make_id',
                'fitment_model_ids': 'model_id',
                'fitment_year_ids': 'year_id',
                'fitment_submodel_ids': 'submodel_id',
                'fitment_wheel_ids': 'rear_wheels_id',
                'fitment_vehicle_platform_ids': 'vehicle_platform_id',
            }

            selected = {col: [] for col in field_to_col.values()}

            def parse_domain(domain):
                if not domain:
                    return
                for clause in domain:
                    if isinstance(clause, (list, tuple)) and len(clause) == 3:
                        f_name, op, val = clause
                        if f_name in field_to_col:
                            col = field_to_col[f_name]
                            if op in ('in', '=') and val:
                                if isinstance(val, list):
                                    selected[col].extend(val)
                                else:
                                    selected[col].append(val)
                    elif isinstance(clause, list):
                        parse_domain(clause)

            parse_domain(filter_domain)
            parse_domain(search_domain)

            # ── Step 2: Get product ids matching the domain ───────────────
            full_domain = []
            if search_domain:
                full_domain += search_domain
            if filter_domain:
                full_domain += filter_domain

            if full_domain:
                product_ids = self.search(full_domain).ids
            else:
                # No filter — get all valid products
                ctx = self.env.context
                base_domain = [['sale_ok', '=', True], ['type', '!=', 'combo']]
                product_ids = self.search(base_domain).ids

            if not product_ids:
                return {'values': []}

            # ── Step 3: Fitment-level filtering SQL ────────────────────────
            # Map relation table column names to fitment_master columns
            rel_col_to_fm_col = {
                'make_id': 'make_id',
                'model_id': 'model_id',
                'year_id': 'year_id',
                'submodel_id': 'submodel_id',
                'wheel_id': 'rear_wheels_id',
                'platform_id': 'vehicle_platform_id',
            }

            fm_comodel_col = rel_col_to_fm_col[comodel_col]

            # Query fitment_master records linked to the matching products,
            # filtering by selected values of OTHER fitment fields.
            where_clauses = ["cpm.product_id = ANY(%s)"]
            params = [product_ids]

            for col, ids in selected.items():
                if col != fm_comodel_col and ids:
                    where_clauses.append(f"fm.{col} = ANY(%s)")
                    params.append(ids)

            where_str = " AND ".join(where_clauses)

            self.env.cr.execute(f"""
                SELECT
                    fm.{fm_comodel_col}            AS id,
                    c.name                         AS display_name,
                    COUNT(DISTINCT cpm.product_id) AS __count
                FROM cust_prod_master_fitment_obj rel
                INNER JOIN customer_product_master cpm ON cpm.id = rel.cust_pro_master_id
                INNER JOIN fitment_master fm ON fm.id = rel.fitment_id
                INNER JOIN {comodel_table} c ON c.id = fm.{fm_comodel_col}
                WHERE {where_str}
                GROUP BY fm.{fm_comodel_col}, c.name
                HAVING COUNT(DISTINCT cpm.product_id) > 0
                ORDER BY c.name
            """, tuple(params))

            rows = self.env.cr.fetchall()
            return {
                'values': [
                    {'id': r[0], 'display_name': r[1] or '', '__count': r[2]}
                    for r in rows
                ]
            }

        except Exception as e:
            _logger.warning("MMY search_panel_select_multi_range SQL failed for %s: %s", field_name, e)
            kwargs['limit'] = 0
            return super().search_panel_select_multi_range(field_name, **kwargs)