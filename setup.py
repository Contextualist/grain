import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="grain",
    version="0.6.2",
    author="Harry Zhang",
    author_email="zhanghar@iu.edu",
    description="A scheduler for resource-aware parallel computing on clusters.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.iu.edu/zhanghar/grain",
    packages=setuptools.find_packages(),
    install_requires=[
        "trio",
        "pynng",
        "dill",
    ],
    python_requires=">=3.6",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Framework :: Trio",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.6",
        "Topic :: Scientific/Engineering",
        "Topic :: System :: Distributed Computing",
    ],
)
