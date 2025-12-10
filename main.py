from flask import Flask, request, jsonify
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')

from routes import *

if __name__ == '__main__':
    app.run(debug=True)
