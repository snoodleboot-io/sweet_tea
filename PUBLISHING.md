# PyPI Publishing Setup Guide

This guide explains how to set up PyPI publishing for the Sweet Tea Factory System.

## 🚀 Quick Setup

### 1. Create PyPI Accounts

1. **Production PyPI**: https://pypi.org/
   - Create account for `snoodleboot`
   - Generate API token at: https://pypi.org/manage/account/token/

2. **TestPyPI**: https://test.pypi.org/
   - Create account for testing
   - Generate API token at: https://test.pypi.org/manage/account/token/

### 2. Add GitHub Secrets

Go to: **Repository → Settings → Secrets and variables → Actions**

Add these secrets:
- `PYPI_API_TOKEN`: Your production PyPI token
- `TEST_PYPI_API_TOKEN`: Your TestPyPI token

### 3. Test Publishing

1. **Push to main branch** → Automatically publishes to TestPyPI
2. **Create GitHub release** → Publishes to production PyPI

## 📋 Package Metadata

The package is fully configured with:
- ✅ Complete author/maintainer information
- ✅ License (Apache-2.0)
- ✅ Comprehensive classifiers
- ✅ Homepage and documentation URLs
- ✅ Keywords and descriptions

## 🔄 Publishing Workflow

### TestPyPI (Automatic on main branch)
- Triggers on every push to `main`
- Publishes to https://test.pypi.org/project/sweet-tea/
- Safe for testing: `pip install --index-url https://test.pypi.org/simple/ sweet-tea`

### Production PyPI (Manual releases)
- Triggers only on GitHub releases
- Publishes to https://pypi.org/project/sweet-tea/
- Production ready: `pip install sweet-tea`

## 🧪 Testing Your Setup

### Install from TestPyPI
```bash
pip install --index-url https://test.pypi.org/simple/ sweet-tea
```

### Verify Installation
```python
from sweet_tea import Registry, Factory, AbstractFactory, SingletonFactory

# Test basic functionality
class TestService:
    def __init__(self, name="test"):
        self.name = name

Registry.register("test_service", TestService)
instance = Factory.create("test_service")
print(f"✅ Factory works: {instance.name}")
```

## 📝 Release Process

1. **Update version** in `pyproject.toml`
2. **Create git tag**: `git tag v0.1.3 && git push origin v0.1.3`
3. **Create GitHub release** with tag
4. **Publishing happens automatically**

## 🔧 Troubleshooting

### Publishing Fails
- Check if API tokens are set correctly
- Verify token has upload permissions
- Check if version number is unique

### Import Errors
- Ensure all dependencies are listed in `pyproject.toml`
- Test installation in clean virtual environment

### Build Errors
- Run `uv build` locally to test
- Check for missing files in package

## 📞 Support

For publishing issues, check:
- GitHub Actions logs
- PyPI account settings
- Token permissions
