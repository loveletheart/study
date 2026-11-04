class WeatherError(Exception):
    """날씨 조회 기능의 공개 오류 계약."""


class InvalidWeatherQueryError(WeatherError):
    pass


class WeatherProviderUnavailableError(WeatherError):
    pass


class WeatherProviderTimeoutError(WeatherError):
    pass


class WeatherProviderDataError(WeatherError):
    pass


class WeatherRateLimitError(WeatherError):
    pass
