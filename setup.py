from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="wildfire-monitoring-system",
    version="1.0.0",
    author="Wildfire Team",
    author_email="info@example.com",
    description="Yangın İzleme ve Tahmini Sistemi",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Rum-eysa/EmberMind",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Scientific/Engineering",
    ],
    python_requires=">=3.9",
    install_requires=[
        "fastapi==0.104.1",
        "uvicorn[standard]==0.24.0",
        "python-dotenv==1.0.0",
        "requests==2.31.0",
        "pandas==2.0.3",
        "numpy==1.26.4",
        "geopandas==0.13.0",
        "shapely==2.0.1",
        "scikit-learn==1.3.0",
        "scipy==1.11.1",
        "tensorflow==2.16.1",
        "xgboost==1.7.5",
        "SQLAlchemy==2.0.19",
        "psycopg2-binary==2.9.9",
        "alembic==1.11.1",
        "redis==4.6.0",
        "celery==5.3.1",
        "pydantic==2.0.2",
    ],
)
