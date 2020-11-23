import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="grain-scheduler",
    version="0.14.0",
    author="Harry Zhang",
    author_email="zhanghar@iu.edu",
    description="A scheduler for resource-aware parallel computing on clusters.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.iu.edu/zhanghar/grain",
    packages=setuptools.find_packages(),
    python_requires=">=3.7",
    install_requires=[
        "trio >= 0.15.0",
        "dill >= 0.3.2",
        "msgpack",
        "toml >= 0.10.1",
        "click",
        "psutil",
    ],
    tests_require = [
        "pytest",
        "pytest-trio",
    ],
    entry_points = {
        "console_scripts": ["grain=grain.cli:main"],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Framework :: Trio",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Topic :: Scientific/Engineering",
        "Topic :: System :: Distributed Computing",
    ],
)
