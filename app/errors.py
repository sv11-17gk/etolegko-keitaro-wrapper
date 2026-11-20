# -*- coding: utf-8 -*-
"""Ошибки доменного слоя; роуты переводят их в HTTP-статусы."""


class AppError(Exception):
    status = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFound(AppError):
    status = 404


class Conflict(AppError):
    status = 409


class KtUpstreamError(AppError):
    """Ошибка при обращении к API Keitaro (KtError из клиента)."""
    status = 502
