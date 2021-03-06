[![Build Status](https://travis-ci.org/eonpatapon/contrail-api-cli.svg?branch=master)](https://travis-ci.org/eonpatapon/contrail-api-cli)

contrail-api-cli
================
Simple CLI program to browse Contrail API server

## Installation

You can install contrail-api-cli inside a python virtualenv. 
First create the virtualenv and install contrail-api-cli with pip.

    $ virtualenv contrail-api-cli-venv
    $ source contrail-api-cli-venv/bin/activate
    (contrail-api-cli-venv) $ pip install contrail-api-cli

## Usage

Run ``contrail-api-cli`` to start the cli. Use the ``-h`` option to see all supported options. By default it will try to connect to ``localhost`` on port ``8082`` with no authentication.
    
Type ``help`` to get the list of all available commands.

Here is a screenshot of an example session:

![Example session](http://i.imgur.com/X83FVTJ.png)

## Authentication

``contrail-api-cli`` supports keystone (v2, v3) and Basic HTTP authentication mechanisms.

When running the contrail API server with ``--auth keystone`` you can login on port 8082 with keystone auth and on port 8095 with basic http auth.

### Basic HTTP auth

    contrail-api-cli --host localhost:8095 --os-auth-plugin http --os-username admin --os-password contrail123

The username and password can be sourced from the environment variables ``OS_USERNAME``, ``OS_PASSWORD``.

The auth plugin default to ``http`` unless ``OS_AUTH_PLUGIN`` is set.

### Kerberos auth

The easiest way is to source your openstack openrc file and run

    contrail-api-cli --os-auth-plugin [v2password|v3password]

See ``contrail-api-cli --os-auth-plugin [v2password|v3password] --help`` for all options.

## What if

### virtualenv is missing

Install virtualenv

    # pip install virtualenv

### pip is missing

Install pip

    # easy_install pip
