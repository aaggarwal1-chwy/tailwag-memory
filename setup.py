from setuptools import find_packages, setup


setup(
    name="tailwag-memory",
    version="0.1.0",
    description="Neo4j-only hybrid memory mockup with mocked OpenAI-style embeddings.",
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=3.11",
    install_requires=[
        "neo4j>=5.20.0",
        "slack-sdk>=3.27.0",
    ],
    extras_require={
        "dev": [
            "pytest>=8.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "tailwag=tailwag_memory.cli:main",
        ],
    },
)
