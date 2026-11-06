from app.common.errors.codes import ErrorCode
from app.common.errors.exceptions import AppError


class RegionNotConfiguredError(AppError):
    """공식 경계 조회에 필요한 인증 키 미설정."""

    error_code = ErrorCode.WEATHER_REGION_NOT_CONFIGURED


class WeatherError(AppError):
    """날씨 조회 기능의 공개 오류 계약."""

    error_code = ErrorCode.WEATHER_INVALID_RESPONSE


class InvalidWeatherQueryError(WeatherError):
    """검색어, 조회 개수 또는 좌표가 조회 조건을 만족하지 않는다."""

    error_code = ErrorCode.WEATHER_INVALID_QUERY


class WeatherProviderUnavailableError(WeatherError):
    """외부 날씨 제공사에 연결하지 못했거나 제공사에서 서버 오류가 발생했다."""

    error_code = ErrorCode.WEATHER_UNAVAILABLE


class WeatherProviderTimeoutError(WeatherError):
    """외부 날씨 API가 제한 시간 안에 응답하지 않았다."""

    error_code = ErrorCode.WEATHER_TIMEOUT


class WeatherProviderDataError(WeatherError):
    """제공사의 응답 형식·단위·날짜 또는 필수 데이터가 올바르지 않다."""

    error_code = ErrorCode.WEATHER_INVALID_RESPONSE


class WeatherRateLimitError(WeatherError):
    """외부 날씨 제공사의 요청 한도를 초과했다."""

    error_code = ErrorCode.WEATHER_RATE_LIMITED
