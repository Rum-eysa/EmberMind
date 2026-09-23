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
    url="https://github.com/yourusername/wildfire-monitoring-system",
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
        "Flask==2.3.2",
        "pandas==2.0.3",
        "numpy==1.24.3",
        "scikit-learn==1.3.0",
        "SQLAlchemy==2.0.19",
    ],
)
