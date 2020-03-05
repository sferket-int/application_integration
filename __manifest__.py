# -*- encoding: utf-8 -*-
##############################################################################
#
#    open2bizz
#    Copyright (C) 2017 open2bizz (open2bizz.nl).
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
{
    'name': 'Application Integration',
    'version': '0.2',
    'category': 'Tools',
    'description': """Framework for interfacing data from other applications.""",
    'author': 'Open2bizz',
    'website': 'http://open2bizz.nl/',
    'depends': ['base', 'mail'],
    'init_xml': [],
    'data': [
        'wizard/application_integration_wizard_view.xml',
        'views/application_integration_view.xml',
        'views/application_integration_menu.xml',
        'security/application_integration_security.xml',
        'security/ir.model.access.csv',
    ],
    'demo_xml': [],
    'installable': True,
}
