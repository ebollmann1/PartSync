# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import xlrd
import base64
import re
from odoo import fields, models, _
from odoo.exceptions import UserError
from odoo.tools import SQL
import logging

_logger = logging.getLogger(__name__)


class ImportFitmentMaster(models.TransientModel):
    _name = 'import.fitment.master'
    _description = 'Import Fitment Master'

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

    def _get_records(self, model, domain, name=False, is_create=False):
        """
        Get a record from a model based on domain.
        If no record exists and `is_create=True`, create a new record with the given name.

        :param model: model name (string)
        :param domain: search domain (list of tuples)
        :param name: name to create if record does not exist
        :param is_create: boolean, whether to create if not found
        :return: recordset (singleton)
        """
        model_obj = self.env[model]


        # Search for the first matching record
        record = model_obj.search(domain, limit=1)
        if not record and name:
            record = model_obj.search([('name', '=', self.smart_title_case(name))], limit=1)
        # # If not found and allowed, create a new record
        # if not record and is_create and name:
        #     record = model_obj.create({'name': name})

        return record

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
                year_index = make_index = model_index = submodel_index = rear_wheels_index = vehicle_platform_index = False
                column = sheet_values[0]
                for index, value in enumerate(column):
                    if value == 'Year':
                        year_index = index
                    if value == 'Make':
                        make_index = index
                    if value == 'Model':
                        model_index = index
                    if value == 'Submodel':
                        submodel_index = index
                    if value == 'Wheel Configuration':
                        rear_wheels_index = index
                    if value == 'Vehicle Platform':
                        vehicle_platform_index = index
                    _logger.warning(">\n>>>>>>>>>>>>. Sequence  %s: %s", index, value)
                for sheet_data in sheet_values[1:]:
                    cnt += 1
                    _logger.info(">\n\n\n\n>>>>>>>>>>>>. sheet data  %s, %s, %s", len(sheet_values), cnt, sheet_data)
                    year = make = model = submodel = rear_wheels = vehicle_platform = ''
                    if year_index or year_index == 0:
                        if sheet_data[year_index] and isinstance(sheet_data[year_index], float):
                            year = sheet_data[year_index] and int(sheet_data[year_index]) or False
                        else:
                            year = sheet_data[year_index] and int(sheet_data[year_index]) or False
                    
                    if make_index or make_index == 0:
                        if sheet_data[make_index] and isinstance(sheet_data[make_index], float):
                            make = sheet_data[make_index] and int(sheet_data[make_index]) or False
                        else:
                            make = sheet_data[make_index] and sheet_data[make_index] or False
                    
                    if model_index or model_index == 0:
                        if sheet_data[model_index] and isinstance(sheet_data[model_index], float):
                            model = sheet_data[model_index] and int(sheet_data[model_index]) or False
                        else:
                            model = sheet_data[model_index] and sheet_data[model_index] or False
                    
                    if submodel_index or submodel_index == 0:
                        if sheet_data[submodel_index] and isinstance(sheet_data[submodel_index], float):
                            submodel = sheet_data[submodel_index] and int(sheet_data[submodel_index]) or False
                        else:
                            submodel = sheet_data[submodel_index] and sheet_data[submodel_index] or False
                    
                    if rear_wheels_index or rear_wheels_index == 0:
                        if sheet_data[rear_wheels_index] and isinstance(sheet_data[rear_wheels_index], float):
                            rear_wheels = sheet_data[rear_wheels_index] and int(sheet_data[rear_wheels_index]) or False
                        else:
                            rear_wheels = sheet_data[rear_wheels_index] and sheet_data[rear_wheels_index] or False
                    
                    if vehicle_platform_index or vehicle_platform_index == 0:
                        if sheet_data[vehicle_platform_index] and isinstance(sheet_data[vehicle_platform_index], float):
                            vehicle_platform = sheet_data[vehicle_platform_index] and int(sheet_data[vehicle_platform_index]) or False
                        else:
                            vehicle_platform = sheet_data[vehicle_platform_index] and sheet_data[vehicle_platform_index] or False

                    if year or make or model or submodel or rear_wheels or vehicle_platform:
                        domain = []
                        year_id, make_id, model_id, submodel_id, rear_wheels_id, vehicle_id = False, False, False, False, False, False
                        if year:
                            year_id = self._get_records('fitment.year', [('name', '=', year)], name=year, is_create=True)
                            domain.append(('year_id', '=', year_id.id))
                        else:
                            domain.append(('year_id', '=', False))

                        if make:
                            if isinstance(make, int):
                                make = str(make)
                            make = (make or '').strip()
                            make_id = self._get_records('fitment.make', [('name', '=', make)], name=make, is_create=True)
                            domain.append(('make_id', '=', make_id.id))
                        else:
                            domain.append(('make_id', '=', False))

                        if model:
                            if isinstance(model, int):
                                model = str(model)
                            model = (model or '').strip()
                            model_id = self._get_records('fitment.model', [('name', '=', model)], name=model, is_create=True)
                            domain.append(('model_id', '=', model_id.id))
                        else:
                            domain.append(('model_id', '=', False))

                        if submodel:
                            if isinstance(submodel, int):
                                submodel = str(submodel)
                            submodel = (submodel or '').strip()
                            submodel_id = self._get_records('fitment.submodel', [('name', '=', submodel)], name=submodel, is_create=True)
                            domain.append(('submodel_id', '=', submodel_id.id))
                        else:
                            domain.append(('submodel_id', '=', False))
                            
                        if rear_wheels:
                            if isinstance(rear_wheels, int):
                                rear_wheels = str(rear_wheels)
                            rear_wheels = (rear_wheels or '').strip()
                            rear_wheels_id = self._get_records('fitment.rear.wheels', [('name', '=', rear_wheels)], name=rear_wheels, is_create=True)
                            domain.append(('rear_wheels_id', '=', rear_wheels_id.id))
                        else:
                            domain.append(('rear_wheels_id', '=', False))

                        if vehicle_platform:
                            if isinstance(vehicle_platform, int):
                                vehicle_platform = str(vehicle_platform)
                            vehicle_platform = (vehicle_platform or '').strip()
                            vehicle_id = self._get_records('vehicle.platform', [('name', '=', vehicle_platform)], name=vehicle_platform, is_create=True)
                            domain.append(('vehicle_platform_id', '=', vehicle_id.id))
                        else:
                            domain.append(('vehicle_platform_id', '=', False))
                        
                        fitment_id = self._get_records('fitment.master', domain)
                        _logger.info("\n --------Exiting----- Import fitment_id  %s", fitment_id)
                        vals = {
                            'year_id': year_id and year_id.id or False,
                            'model_id': model_id and model_id.id or False,
                            'make_id': make_id and make_id.id or False,
                            'submodel_id': submodel_id and submodel_id.id or False,
                            'rear_wheels_id': rear_wheels_id and rear_wheels_id.id or False,
                            'vehicle_platform_id': vehicle_id and vehicle_id.id or '',
                        }
                        if not fitment_id and year_id and make_id and model_id:
                            fitment_id = self.env['fitment.master'].create(vals)
                            _logger.info("\n --------New----- Import fitment_id  %s", fitment_id)
                    self._cr.commit()
            _logger.info("\nImport End. ")
        except Exception as e:
            _logger.info("Exception occurred while processing sheet: {}".format(e))
            raise UserError(_("Exception occurred while processing sheet. %s", e))
