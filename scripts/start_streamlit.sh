#!/usr/bin/env sh
set -eu

exec streamlit run streamlit_app/app.py --server.address 0.0.0.0 --server.port 8501
