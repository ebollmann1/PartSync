# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from . import models
from . import wizard
from . import tools

import odoo
if odoo.tools.config['test_enable']:
    from . import tests
