FROM python:3.13-alpine
# WeasyPrint system deps (pango/cairo stack) + fonts for the PDF reports
RUN apk add --no-cache pango gdk-pixbuf libffi ttf-dejavu
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
COPY textes/ textes/
COPY static/ static/
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
