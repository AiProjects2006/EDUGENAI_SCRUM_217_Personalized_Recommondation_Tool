FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py models.py student_data_collection.py README.md ./

EXPOSE 8001

CMD ["python", "-c", "import config, models, student_data_collection; print('Personalized Recommendation Tool ready')"]
