from odoo import models, fields, api
import xlrd
import base64
from odoo import fields, models, _
from odoo.exceptions import UserError
from odoo.tools import SQL
import logging
_logger = logging.getLogger(__name__)


class ImportVikingProductAttribute(models.TransientModel):
    _name = 'import.viking.product'
    _description = 'Import Viking Product Attribute'

    file = fields.Binary(required=True, string="XLSX File")
    filename = fields.Char()

    def action_import(self):
        if not self.file:
            raise UserError(_('Error!', "Please Select a File"))
        work_book = xlrd.open_workbook(file_contents=base64.decodebytes(self.file))
        sheet = work_book.sheet_by_index(0)
        row_count = sheet.nrows
        col_count = sheet.ncols
        print("\n ++++++++ row_count ++++++", row_count)
        print("\n ++++++++ col_count ++++++", col_count)

        #  ----------- Product Variant ---------
        product_product_dict = {}
        product_data = self.env['product.product'].search_read([], fields=['default_code', 'id'])
        for pr in product_data:
            if pr.get('default_code') not in product_product_dict:
                product_product_dict[pr.get('default_code')] = pr.get('id')

        product_product_dict_2 = {}
        product_data_2 = self.env['product.product'].search_read([], fields=['product_tmpl_id', 'id'])
        for pr2 in product_data_2:
            if pr2.get('id') not in product_product_dict_2:
                product_product_dict_2[pr2.get('id')] = pr2.get('product_tmpl_id')[0]

        attribute_line_dict = {}
        attribute_line_data = self.env['product.template.attribute.line'].search_read([], fields=['product_tmpl_id', 'attribute_id', 'id'])

        for ald in attribute_line_data:
            key = ''
            if ald.get('product_tmpl_id'):
                key = str(ald.get('product_tmpl_id')[0])
            if ald.get('attribute_id'):
                if key:
                    key += '-' + str(ald.get('attribute_id')[0])
                else:
                    key = str(ald.get('attribute_id'))

            if key not in attribute_line_dict:
                attribute_line_dict[key] = ald.get('id')

        # ---------- Attributes -----------------
        attribute_dict = {}
        attribute_data = self.env['product.attribute'].search_read([], fields=['name', 'id'])
        for ad in attribute_data:
            if ad.get('name') not in attribute_dict:
                attribute_dict[ad.get('name')] = ad.get('id')

        # ---------- Attributes Value -----------------
        attribute_value_dict = {}
        attribute_value_data = self.env['product.attribute.value'].search_read([], fields=['name', 'attribute_id', 'id'])
        for avd in attribute_value_data:
            if avd.get('attribute_id'):
                key = str(avd.get('attribute_id')[0]) + "-" + avd.get('name')
                if key not in attribute_value_dict:
                    attribute_value_dict[key] = avd.get('id')

        count=2
        for cur_row in range(1, row_count):
            product_product_id = False
            Ride_height_attribute = Shock_body_attribute = Product_line_attribute = Adjustable_DA_TA_attribute = False
            Ride_height_attribute_value = Shock_body_attribute_value = Product_line_attribute_value = Adjustable_DA_TA_attribute_value = False
            for cur_col in range(0, col_count):
                header_cell = sheet.cell(0, cur_col)
                cell = sheet.cell(cur_row, cur_col)
                if header_cell.value == 'Internal Reference' and cell.value:
                    if cell.value in product_product_dict:
                        product_product_id = product_product_dict.get(cell.value)
                # +++++++++++++++++++++++++ Attribute Code +++++++++++++++++++++++++++++++++++++++++++++++++
                if header_cell.value == 'Ride Height' and 'Ride Height' and attribute_dict:
                    Ride_height_attribute = attribute_dict.get('Ride Height')
                    key = str(Ride_height_attribute) + '-' + cell.value
                    if key in attribute_value_dict and Ride_height_attribute:
                        Ride_height_attribute_value = attribute_value_dict.get(key)

                if header_cell.value == 'Shock Body' and 'Shock Body' and attribute_dict:
                    Shock_body_attribute = attribute_dict.get('Shock Body')
                    key = str(Shock_body_attribute) + '-' + cell.value
                    if key in attribute_value_dict and Shock_body_attribute:
                        Shock_body_attribute_value = attribute_value_dict.get(key)

                if header_cell.value == 'Product Line' and 'Product Line' and attribute_dict:
                    Product_line_attribute = attribute_dict.get('Product Line')
                    key = str(Product_line_attribute) + '-' + cell.value
                    if key in attribute_value_dict and Product_line_attribute:
                        Product_line_attribute_value = attribute_value_dict.get(key)

                if header_cell.value == 'Adjustable DA / TA' and 'Adjustable DA / TA' and attribute_dict:
                    Adjustable_DA_TA_attribute = attribute_dict.get('Adjustable DA / TA')
                    key = str(Adjustable_DA_TA_attribute) + '-' + cell.value
                    if key in attribute_value_dict and Adjustable_DA_TA_attribute:
                        Adjustable_DA_TA_attribute_value = attribute_value_dict.get(key)

            if product_product_id:
                product_tmpl_id = product_product_dict_2.get(product_product_id, False)
                if product_tmpl_id:
                    if Ride_height_attribute and Ride_height_attribute_value:
                        key = str(product_tmpl_id) + '-' + str(Ride_height_attribute)
                        if key in attribute_line_dict:
                            attribute_line_id = attribute_line_dict[key]
                            attribute_line_id = self.env['product.template.attribute.line'].browse(attribute_line_id)
                            attribute_line_id.write({
                                'value_ids': [(4, Ride_height_attribute_value)]
                            })
                        else:
                            attribute_line_id = self.env['product.template.attribute.line'].create({
                                'attribute_id': Ride_height_attribute,
                                'product_tmpl_id': product_tmpl_id,
                                'value_ids': [(4, Ride_height_attribute_value)]
                            })
                            attribute_line_dict[key] = attribute_line_id.id

                    if Shock_body_attribute and Shock_body_attribute_value:
                        key = str(product_tmpl_id) + '-' + str(Shock_body_attribute)
                        if key in attribute_line_dict:
                            attribute_line_id = attribute_line_dict[key]
                            attribute_line_id = self.env['product.template.attribute.line'].browse(attribute_line_id)
                            attribute_line_id.write({
                                'value_ids': [(4, Shock_body_attribute_value)]
                            })
                        else:
                            attribute_line_id = self.env['product.template.attribute.line'].create({
                                'attribute_id': Shock_body_attribute,
                                'product_tmpl_id': product_tmpl_id,
                                'value_ids': [(4, Shock_body_attribute_value)]
                            })
                            attribute_line_dict[key] = attribute_line_id.id

                    if Product_line_attribute and Product_line_attribute_value:
                        key = str(product_tmpl_id) + '-' + str(Product_line_attribute)
                        if key in attribute_line_dict:
                            attribute_line_id = attribute_line_dict[key]
                            attribute_line_id = self.env['product.template.attribute.line'].browse(attribute_line_id)
                            attribute_line_id.write({
                                'value_ids': [(4, Product_line_attribute_value)]
                            })

                        else:
                            attribute_line_id = self.env['product.template.attribute.line'].create({
                                'attribute_id': Product_line_attribute,
                                'product_tmpl_id': product_tmpl_id,
                                'value_ids': [(4, Product_line_attribute_value)]
                            })
                            attribute_line_dict[key] = attribute_line_id.id

                    if Adjustable_DA_TA_attribute and Adjustable_DA_TA_attribute_value:
                        key = str(product_tmpl_id) + '-' + str(Adjustable_DA_TA_attribute)
                        if key in attribute_line_dict:
                            attribute_line_id = attribute_line_dict[key]
                            attribute_line_id = self.env['product.template.attribute.line'].browse(attribute_line_id)
                            attribute_line_id.write({
                                'value_ids': [(4, Adjustable_DA_TA_attribute_value)]
                            })
                        else:
                            attribute_line_id = self.env['product.template.attribute.line'].create({
                                    'attribute_id': Adjustable_DA_TA_attribute,
                                    'product_tmpl_id': product_tmpl_id,
                                    'value_ids': [(4, Adjustable_DA_TA_attribute_value)]
                                })
                            attribute_line_dict[key] = attribute_line_id.id

            print("\n ++++++++ count ++++++++", count)
            _logger.info("\n +++++++++++ Count ++++++++++%s", count)
            count+=1
        5/0
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': 'Import Completed',
        #         'message': (
        #             f'Categories Created Successfully!\n'
        #             f'Total Created: {total_created}'
        #         ),
        #         'type': 'success',
        #         'sticky': False,
        #         'next': {'type': 'ir.actions.act_window_close'},
        #     }
        # }