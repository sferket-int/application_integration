# -*- encoding: utf-8 -*-
##############################################################################
#
#    open2bizz
#    Copyright (C) 2014 open2bizz (open2bizz.nl).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
from odoo import models, fields, api
from odoo.tools.translate import _

import logging
_logger = logging.getLogger(__name__)

class application_integration_ready(models.TransientModel):
	_name = 'application.integration.data.wizard'
	_description = "Ready to process dataline"
	
	@api.multi
	def set_ready(self, ids,context=None):
		ids = ids.get('active_ids')
		if not ids or len(ids) < 1:
			raise orm.except_orm(_('Error !'), _('You must select at least one data line!'))
		for rec in self.env['application.integration.data'].browse(ids):
			rec.state = 'ready'
		return {"type": "ir.actions.client", "tag": "reload",}
	
class application_integration_cancel(models.TransientModel):
	_name = 'application.integration.data.cancel.wizard'
	_description = "Cancel dataline"
 	
	change_reason = fields.Text('Change reason'
							, required=True
							, help='Please enter a reason for this change')
 	
	@api.multi
	def do_cancel(self, ids,context=None):
		ids = ids.get('active_ids')
		for rec in self.env['application.integration.data'].browse(ids):
			rec.message_post("Cancelled line. Reason for change: %s" % (self.change_reason), context=context)
			rec.state = 'cancel'
 			
		return {"type": "ir.actions.client", "tag": "reload",}

