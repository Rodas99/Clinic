#!/usr/bin/python3
from wsgiref.handlers import CGIHandler

from app import app

import login

connection = psycopg.connect(login.credentials)

CGIHandler().run(app)
