# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import xlrd, re
import base64
import logging

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ImportCustomerProductMaster(models.TransientModel):
    _inherit = 'import.customer.product.master'
    _description = 'Import Customer Product Master'

    import_category = fields.Boolean('Is category Import')

    def smart_title_case(self, text):
        if not text:
            return text

        def convert_word(word):
            if not word:
                return word
            # Has both letters AND digits = code → keep as-is (C10, 2WD, 4X4)
            if re.search(r'[A-Za-z]', word) and re.search(r'\d', word):
                return word
            # All letters only (no digits) → always Title case (FORD→Ford, MAKE→Make, AWD→Awd)
            if re.match(r'^[A-Za-z]+$', word):
                return word.capitalize()
            # Everything else (pure digits, symbols) → unchanged
            return word

        words = text.split()
        result = []
        for word in words:
            match = re.match(r'^(\W*)(.*?)(\W*)$', word)
            prefix, core, suffix = match.group(1), match.group(2), match.group(3)
            result.append(prefix + convert_word(core) + suffix)

        return ' '.join(result)

    def _get_records(self, model, domain, name=''):
        model_obj = self.env[model]
        # Search for the first matching record
        record = model_obj.search(domain, limit=1)
        if not record and name:
            record = model_obj.search([('name', '=', self.smart_title_case(name))], limit=1)

        # if not record and name:
        #     record = model_obj.create({'name': name})

        return record

    def import_data(self):
        """
        Create new record of eCategory object.
        """
        _logger.info("\n ------------- Import Started -> customer.product.master")
        try:
            work_book = self.read_xlx_file()
            cust_pro_obj = self.env['customer.product.master']
            for sheet in work_book._sheet_list:
                sheet_values = sheet._cell_values
                cnt = 1
                for sheet_data in sheet_values[1:]:
                    cnt += 1
                    # this code is use for import categoty but never used again this is onetime
                    if self.import_category:
                        part_categ_name = str(sheet_data[4])
                        _logger.info(">\n>>>>cnt>>>>>>>>. sheet data  %s", cnt)
                        sub_categ_name = str(sheet_data[2])
                        categ_name = str(sheet_data[0])
                        already_part_categ_id = self.env['product.public.category'].search([('name', '=', part_categ_name)], limit=1)
                        already_subcateg_id = self.env['product.public.category'].search([('name', '=', sub_categ_name)], limit=1)
                        already_categ_id = self.env['product.public.category'].search([('name', '=', categ_name)], limit=1)
                        parent_categ_id = self.env['product.public.category'].search([('name', '=', sub_categ_name)])
                        if parent_categ_id and len(parent_categ_id.ids) > 1:
                            parent_categ_id = self.env['product.public.category'].search(
                                [('name', '=', sub_categ_name), ('parent_id','=',already_categ_id.id)])
                        if not already_part_categ_id:
                            self.env['product.public.category'].create({
                                'name':part_categ_name,
                                'parent_id': parent_categ_id.ids[0]
                            })
                    else:
                        _logger.info(">\n\n\n\n>>>>>>>>>>>>. sheet data  %s, %s, %s", len(sheet_values), cnt, sheet_data)
                        customer_code = sheet_data[0] and sheet_data[0] or False
                        company_id = self.env.company and self.env.company or self.env.user.company_id
                        cpm_validation = []
                        cpm_valid_id = False
                        if customer_code:
                            cpm_valid_id = self.env['cpm.validation'].search([('code', '=', customer_code)], limit=1)
                            # cpm_valid_id = self.env['cpm.validation'].search([('name', '=', customer_code)], limit=1)
                            if company_id:
                                company_id = self.env['res.company'].search([('id', '=', company_id.id)])
                                if not cpm_valid_id:
                                    continue
                                if cpm_valid_id.id not in company_id.cpm_validation_ids.ids:
                                    continue

                        product_code = sheet_data[1] and sheet_data[1] or False
                        # year = sheet_data[2] and str(int(sheet_data[2])) or False
                        year = sheet_data[2] and str(sheet_data[2]) or False
                        if sheet_data[2] and isinstance(sheet_data[2], float):
                            year = sheet_data[2] and int(sheet_data[2]) or year
                        make = sheet_data[3] and sheet_data[3] or False

                        if type(make) == float or type(make) == int:
                            make = str(int(make))

                        model = sheet_data[4] and sheet_data[4] or False
                        if type(model) == float or type(model) == int:
                            model = str(int(model))

                        submodel = sheet_data[5] and sheet_data[5] or False
                        if type(submodel) == float or type(submodel) == int:
                            submodel = str(int(submodel))

                        rear_wheels = sheet_data[6] and sheet_data[6] or False
                        if type(rear_wheels) == float or type(rear_wheels) == int:
                            rear_wheels = str(int(rear_wheels))

                        vehicle_platform = sheet_data[7] and sheet_data[7] or False
                        if type(vehicle_platform) == float or type(vehicle_platform) == int:
                            vehicle_platform = str(int(vehicle_platform))

                        vehicle_id = False
                        fitment_id = False
                        product_id = False
                        if self.product_type == 'name':
                            product_id = self.env['product.product'].search([('name', '=', product_code)], limit=1)
                        if self.product_type == 'code':
                            product_id = self.env['product.product'].search([('default_code', '=', product_code)], limit=1)
                        if product_id:
                            if vehicle_platform:
                                vehicle_id = self.env['vehicle.platform'].search([('name', '=', vehicle_platform)], limit=1)
                                # if not vehicle_id:
                                #     vehicle_id = self.env['vehicle.platform'].create({'name': vehicle_platform})

                            _logger.info(">\n>>    vehicle_id   >>>>>>>>>>product_id. vehicle_id   %s, %s ", product_id,
                                         vehicle_id)
                            if year or make or model or submodel or rear_wheels or vehicle_platform:
                                domain = []
                                year_id = False
                                make_id = False
                                model_id = False
                                submodel_id = False
                                rear_wheels_id = False
                                vehicle_id = False
                                if year:
                                    year_id = self._get_records('fitment.year', [('name', '=', year)], name=year)
                                    domain.append(('year_id', '=', year_id.id))
                                else:
                                    domain.append(('year_id', '=', False))

                                if make:
                                    if isinstance(make, int):
                                        make = str(make)
                                    make = (make or '').strip()
                                    make_id = self._get_records('fitment.make', [('name', '=', make)], name=make)
                                    domain.append(('make_id', '=', make_id.id))
                                else:
                                    domain.append(('make_id', '=', False))

                                if model:
                                    if isinstance(model, int):
                                        model = str(model)
                                    model = (model or '').strip()
                                    model_id = self._get_records('fitment.model', [('name', '=', model)], name=model)
                                    domain.append(('model_id', '=', model_id.id))
                                else:
                                    domain.append(('model_id', '=', False))

                                if submodel:
                                    if isinstance(submodel, int):
                                        submodel = str(submodel)
                                    submodel = (submodel or '').strip()
                                    submodel_id = self._get_records('fitment.submodel', [('name', '=', submodel)],
                                                                    name=submodel)
                                    domain.append(('submodel_id', '=', submodel_id.id))
                                else:
                                    domain.append(('submodel_id', '=', False))

                                if rear_wheels:
                                    if isinstance(rear_wheels, int):
                                        rear_wheels = str(rear_wheels)
                                    rear_wheels = (rear_wheels or '').strip()
                                    rear_wheels_id = self._get_records('fitment.rear.wheels',
                                                                       [('name', '=', rear_wheels)], name=rear_wheels)
                                    domain.append(('rear_wheels_id', '=', rear_wheels_id.id))
                                else:
                                    domain.append(('rear_wheels_id', '=', False))

                                if vehicle_platform:
                                    if isinstance(vehicle_platform, int):
                                        vehicle_platform = str(vehicle_platform)
                                    vehicle_platform = (vehicle_platform or '').strip()
                                    vehicle_id = self._get_records('vehicle.platform',
                                                                   [('name', '=', vehicle_platform)],
                                                                   name=vehicle_platform)
                                    domain.append(('vehicle_platform_id', '=', vehicle_id.id))
                                else:
                                    domain.append(('vehicle_platform_id', '=', False))

                                fitment_id = self.env['fitment.master'].sudo().search(domain, limit=1)
                                if not fitment_id and year_id and make_id and model_id:
                                    vals = {
                                        'year_id': year_id and year_id.id or False,
                                        'model_id': model_id and model_id.id or False,
                                        'make_id': make_id and make_id.id or False,
                                        'submodel_id': submodel_id and submodel_id.id or False,
                                        'rear_wheels_id': rear_wheels_id and rear_wheels_id.id or False,
                                        'vehicle_platform_id': vehicle_id and vehicle_id.id or '',
                                    }
                                    fitment_id = self.env['fitment.master'].sudo().create(vals)
                            cust_pro_id = cust_pro_obj.search([
                                ('cpm_validation_id', '=', cpm_valid_id.id),
                                ('product_id', '=', product_id.id)], limit=1)
                            if fitment_id and cust_pro_id:
                                vals = {
                                    'fitment_ids': [(4, fitment_id.id)]
                                }
                                cust_pro_id.write(vals)
                                _logger.info(">\n>>    cust_pro_id   >>>>>   write   >>>>. cust_pro_id    %s  ",
                                             cust_pro_id)
                            if not cust_pro_id and fitment_id:
                                vals = {}
                                if cpm_valid_id:
                                    vals.update({'cpm_validation_id': cpm_valid_id.id})
                                if product_id:
                                    vals.update({'product_id': product_id.id})
                                if product_id and vals:
                                    new_cust_pro_id = cust_pro_obj.create(vals)
                                    if new_cust_pro_id and fitment_id:
                                        new_cust_pro_id.fitment_ids = [(4, fitment_id.id)]
                                    _logger.info(">\n>>    new_cust_pro_id   >>>>>>>>>>. new_cust_pro_id    %s  ", new_cust_pro_id)
            _logger.info("\nImport End. ")
        except Exception as e:
            _logger.info("Exception occurred while processing sheet: {}".format(e))
            raise UserError(_("Exception occurred while processing sheet. %s", e))
