FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY personalized_recommendation_tool ./personalized_recommendation_tool
COPY README.md .

EXPOSE 8001

CMD ["python", "-c", "import personalized_recommendation_tool; print('Personalized Recommendation Tool ready')"]
