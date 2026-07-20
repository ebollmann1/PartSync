# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import xlrd
import base64

from odoo import fields, models, _
from odoo.exceptions import UserError

import logging

_logger = logging.getLogger(__name__)


class ImportFitmentdata(models.TransientModel):
    _name = 'import.fitment.data'
    _description = 'Import Fitment Data'

    data_type = fields.Selection([
        ('year', 'Year'),
        ('make', 'Make'),
        ('model', 'Model'),
        ('submodel', 'Submodel'),
        ('rear_wheels', 'Wheel Configuration')
    ])
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
        _logger.info("\n ------------- Import Started -> Fitment")
        try:
            work_book = self.read_xlx_file()
            for sheet in work_book._sheet_list:
                sheet_values = sheet._cell_values
                cnt = 1
                for sheet_data in sheet_values[1:]:
                    cnt += 1
                    _logger.info(">\n\n\n\n>>>>>>>>>>>>. sheet data  %s, %s, %s", len(sheet_values), cnt, sheet_data)
                    if sheet_data[0] and self.data_type == 'year':
                        year = sheet_data[0] and str(sheet_data[0]) or False
                        year_id = self.env['fitment.year'].search([('name', '=', year)])
                        if not year_id:
                            self.env['fitment.year'].create({'name': year})
                    if sheet_data[0] and self.data_type == 'make':
                        make = sheet_data[0] and sheet_data[0] or False
                        make_id = self.env['fitment.make'].search([('name', '=', make)])
                        if not make_id:
                            self.env['fitment.make'].create({'name': make})

                    if sheet_data[0] and self.data_type == 'model':
                        model = sheet_data[0] and sheet_data[0] or False
                        model_id = self.env['fitment.model'].search([('name', '=', model)])
                        if not model_id:
                            self.env['fitment.model'].create({'name': model})

                    if sheet_data[0] and self.data_type == 'submodel':
                        submodel = sheet_data[0] and sheet_data[0] or False
                        submodel_id = self.env['fitment.submodel'].search([('name', '=', submodel)])
                        if not submodel_id:
                            self.env['fitment.submodel'].create({'name': submodel})
                    
                    if sheet_data[0] and self.data_type == 'rear_wheels':
                        rear_wheels = sheet_data[0] and sheet_data[0] or False
                        rear_wheels_id = self.env['fitment.rear.wheels'].search([('name', '=', rear_wheels)])
                        if not rear_wheels_id:
                            self.env['fitment.rear.wheels'].create({'name': rear_wheels})
                    
            _logger.info("\nImport End. ")
        except Exception as e:
            _logger.info("Exception occurred while processing sheet: {}".format(e))
            raise UserError(_("Exception occurred while processing sheet. %s", e))
