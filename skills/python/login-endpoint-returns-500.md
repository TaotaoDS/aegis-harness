---
category: python
id: login-endpoint-returns-500
source_solution: e2bda9aa
triggers:
- python
- auth
type: error_fix
version: 1
---

## Problem
Login endpoint returns 500

## Symptoms
Error 500 on /api/login

## Failed Approaches
restart server → config unchanged

## Solution
Set SECRET_KEY in environment

## Root Cause
missing env var

## Tags
python, auth
