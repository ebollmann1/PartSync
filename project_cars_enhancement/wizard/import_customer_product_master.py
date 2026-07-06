# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import xlrd
import base64
import logging

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ImportCustomerProductMaster(models.TransientModel):
    _name = 'import.customer.product.master'
    _description = 'Import Customer Product Master'

    product_type = fields.Selection([('name', 'Name'), ('code', 'Internal Refernce')], string='Product ')
    file_path = fields.Char(string='File Path')
    xls_file = fields.Binary(attachment=True, string='XLS File')
    filename = fields.Char()

    def read_xlx_file(self):
        '''
         cursereate Temp xlx file
        '''
        if not self.xls_file:
            raise UserError(_('Error!', "Please Select a File"))
        else:
            work_book = xlrd.open_workbook(file_contents=base64.decodebytes(self.xls_file))
        return work_book

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
                    # this code is use for import category but never used again this is onetime
                    
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
                        if year or make or model or submodel or rear_wheels:
                            domain = []
                            if year:
                                domain.append(('year_id.name', '=', year))
                            if make:
                                domain.append(('make_id.name', '=', make))
                            if model:
                                domain.append(('model_id.name', '=', model))
                            if submodel:
                                domain.append(('submodel_id.name', '=', submodel))
                            if rear_wheels:
                                domain.append(('rear_wheels_id.name', '=', rear_wheels))
                            if vehicle_id:
                                domain.append(('vehicle_platform_id', '=', vehicle_id.id))
                            fitment_id = self.env['fitment.master'].sudo().search(domain, limit=1)
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
                        if not cust_pro_id:
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
