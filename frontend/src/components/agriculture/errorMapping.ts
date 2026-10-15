/**
 * Farmer-Friendly Persian Error Mapping Architecture
 *
 * Requirements:
 * - Stable error codes mapped to clear, respectful Persian messages for farmers.
 * - Raw exception text, stack traces, and technical dumps separated for Developer Mode.
 * - Expected data unavailability surfaced as guidance, not alarming crashes.
 */

import { ApiError } from '../../api/client.ts';

export interface PersianErrorMapping {
  code: string;
  titleFa: string;
  messageFa: string;
  suggestedActionFa: string;
  rawError?: string;
  technicalDetails?: string;
}

export const ERROR_CODE_MAP: Record<string, { titleFa: string; messageFa: string; suggestedActionFa: string }> = {
  ERR_GEE_UNAVAILABLE: {
    titleFa: 'سرویس ماهواره‌ای موقتاً در دسترس نیست',
    messageFa: 'ارتباط پردازشی با موتور پردازش تصاویر ماهواره‌ای برقرار نشد.',
    suggestedActionFa: 'لطفاً چند دقیقه دیگر مجدداً تلاش فرمایید. در صورت تداوم، محدوده تحلیل را کوچک‌تر کنید.',
  },
  ERR_GEE_TIMEOUT: {
    titleFa: 'طولانی شدن زمان پردازش ماهواره‌ای',
    messageFa: 'محاسبه شاخص‌ها برای این محدوده بیش از سقف زمانی مجاز طول کشید.',
    suggestedActionFa: 'محدوده کوچک‌تری از باغ را ترسیم کنید یا بازه زمانی را به یک یا دو ماه محدود فرمایید.',
  },
  ERR_GEE_AUTH_FAILED: {
    titleFa: 'خطای احراز هویت سرویس سنجش از دور',
    messageFa: 'کلید دسترسی سرور به اطلاعات ماهواره‌ای نیاز به بررسی دارد.',
    suggestedActionFa: 'لطفاً با پشتیبانی یا مدیر سیستم تماس حاصل فرمایید.',
  },
  ERR_INVALID_GEOMETRY: {
    titleFa: 'محدوده زمین نامعتبر است',
    messageFa: 'شکل هندسی چندضلعی ترسیم‌شده یا مختصات واردشده دارای تداخل، خودتقاطعی یا ابعاد نامعتبر است.',
    suggestedActionFa: 'لطفاً رئوس چندضلعی محدوده باغ را با دقت روی نقشه بازرسم نمایید.',
  },
  ERR_INVALID_DATE_RANGE: {
    titleFa: 'بازه زمانی نامعتبر است',
    messageFa: 'تاریخ شروع باید قبل از تاریخ پایان بوده و بازه زمانی نمی‌تواند در آینده یا بیش از ۳ سال باشد.',
    suggestedActionFa: 'لطفاً تقویم بازه پایش را با دقت تنظیم فرمایید.',
  },
  ERR_RECORD_NOT_FOUND: {
    titleFa: 'گزارش یا تحلیل یافت نشد',
    messageFa: 'تحلیل درخواستی در حافظه سامانه یافت نشد یا ممکن است پاک شده باشد.',
    suggestedActionFa: 'لطفاً تحلیل جدیدی برای این قطعه باغ اجرا نمایید.',
  },
  ERR_RATE_LIMIT_EXCEEDED: {
    titleFa: 'سقف مجاز تعداد درخواست‌ها',
    messageFa: 'تعداد تحلیل‌های ارسال‌شده بیش از حد مجاز در دقیقه است.',
    suggestedActionFa: 'لطفاً یک دقیقه شکیبایی فرموده و سپس مجدداً تلاش کنید.',
  },
  ERR_DATASET_UNAVAILABLE: {
    titleFa: 'داده‌های ماهواره‌ای سنجنده در دسترس نیست',
    messageFa: 'اطلاعات سنجنده درخواستی برای این موقعیت مکانی در آرشیو یافت نشد.',
    suggestedActionFa: 'بازه زمانی دیگری را انتخاب نمایید.',
  },
  ERR_INSUFFICIENT_DATA: {
    titleFa: 'تصویر ماهواره‌ای بدون ابر یافت نشد',
    messageFa: 'به دلیل پوشش ابری بالا در تاریخ انتخابی، امکان استخراج شاخص‌های نوری میسر نشد.',
    suggestedActionFa: 'لطفاً بازه زمانی را به روزها یا ماه‌های مجاور گسترش دهید.',
  },
  ERR_VALIDATION_FAILED: {
    titleFa: 'اطلاعات ورودی نامعتبر است',
    messageFa: 'یک یا چند پارامتر ورودی فرم تحلیل دارای قالب صحیح نیست.',
    suggestedActionFa: 'مختصات، تاریخ و تنظیمات درخواست را بررسی فرمایید.',
  },
  ERR_NETWORK: {
    titleFa: 'خطا در برقراری ارتباط با سرور',
    messageFa: 'ارتباط مرورگر با سرور سامانه قطع شده است.',
    suggestedActionFa: 'اتصال اینترنت خود را بررسی نموده و صفحه را تازه‌سازی فرمایید.',
  },
  ERR_INTERNAL_SERVER_ERROR: {
    titleFa: 'خطای غیرمنتظره در پردازش',
    messageFa: 'هنگام محاسبه داده‌های ماهواره‌ای خطایی در سرور رخ داد.',
    suggestedActionFa: 'لطفاً چند لحظه بعد مجدداً تلاش فرمایید.',
  },
  ERR_TILE_FORBIDDEN: {
    titleFa: 'دسترسی به کاشی نقشه غیرمجاز است',
    messageFa: 'امضای امنیتی توکن کاشی نامعتبر است یا دستکاری شده است.',
    suggestedActionFa: 'لطفاً لایه نقشه را مجدداً بارگذاری فرمایید.',
  },
  ERR_TILE_EXPIRED: {
    titleFa: 'انقضای توکن کاشی نقشه',
    messageFa: 'مدت اعتبار توکن امنیتی کاشی‌های ماهواره‌ای به پایان رسیده است.',
    suggestedActionFa: 'نقشه به‌طور خودکار توکن جدید دریافت می‌کند؛ در صورت تداوم صفحه را تازه‌سازی فرمایید.',
  },
  ERR_TILE_OUT_OF_BOUNDS: {
    titleFa: 'موقعیت کاشی خارج از محدوده است',
    messageFa: 'بزرگ‌نمایی یا مختصات کاشی خارج از محدوده جغرافیایی مجاز است.',
    suggestedActionFa: 'روی محدوده زمین مورد نظر بزرگ‌نمایی فرمایید.',
  },
  ERR_TILE_RATE_LIMIT: {
    titleFa: 'محدودیت درخواست کاشی نقشه',
    messageFa: 'تعداد درخواست‌های بارگذاری کاشی نقشه از حد مجاز فراتر رفته است.',
    suggestedActionFa: 'لطفاً چند لحظه شکیبایی فرمایید.',
  },
  ERR_TILE_LAYER_EXPIRED: {
    titleFa: 'نشست لایه نقشه منقضی شده است',
    messageFa: 'جلسه بارگذاری لایه نقشه به پایان رسیده است.',
    suggestedActionFa: 'لطفاً لایه مورد نظر را مجدداً انتخاب و بارگذاری فرمایید.',
  },
  ERR_UNAUTHORIZED: {
    titleFa: 'عدم احراز هویت',
    messageFa: 'دسترسی به این بخش از سامانه نیازمند ورود معتبر است.',
    suggestedActionFa: 'لطفاً وارد حساب کاربری خود شوید.',
  },
  ERR_FORBIDDEN: {
    titleFa: 'دسترسی غیرمجاز',
    messageFa: 'شما مجوز دسترسی به این منبع را ندارید.',
    suggestedActionFa: 'با مدیر سامانه تماس حاصل فرمایید.',
  },
  ERR_METHOD_NOT_ALLOWED: {
    titleFa: 'روش درخواست نامعتبر است',
    messageFa: 'متد ارسال درخواست برای این آدرس پشتیبانی نمی‌شود.',
    suggestedActionFa: 'با پشتیبانی سامانه تماس حاصل فرمایید.',
  },
};

/**
 * Maps any error (ApiError, Error, string, etc.) to a safe, farmer-friendly Persian structure.
 */
export function mapErrorToPersian(err: unknown): PersianErrorMapping {
  if (err instanceof ApiError) {
    const known = ERROR_CODE_MAP[err.code] || ERROR_CODE_MAP.ERR_INTERNAL_SERVER_ERROR;
    let technicalDetails = '';
    if (err.detail) {
      technicalDetails = typeof err.detail === 'object' ? JSON.stringify(err.detail, null, 2) : String(err.detail);
    }
    return {
      code: err.code,
      titleFa: known.titleFa,
      messageFa: known.messageFa,
      suggestedActionFa: known.suggestedActionFa,
      rawError: err.message,
      technicalDetails: technicalDetails || `HTTP ${err.status}: ${err.reason}`,
    };
  }

  const str = typeof err === 'string' ? err : err instanceof Error ? err.message : 'Unknown error';

  // Heuristic matching if a raw message reached here
  let code = 'ERR_INTERNAL_SERVER_ERROR';
  if (/network|fetch|failed to fetch/i.test(str)) {
    code = 'ERR_NETWORK';
  } else if (/geometry|polygon|coordinate/i.test(str)) {
    code = 'ERR_INVALID_GEOMETRY';
  } else if (/date|range/i.test(str)) {
    code = 'ERR_INVALID_DATE_RANGE';
  } else if (/earth engine|eeexception|gee/i.test(str)) {
    code = 'ERR_GEE_UNAVAILABLE';
  } else if (/not found|404/i.test(str)) {
    code = 'ERR_RECORD_NOT_FOUND';
  } else if (/rate limit|429/i.test(str)) {
    code = 'ERR_RATE_LIMIT_EXCEEDED';
  }

  const known = ERROR_CODE_MAP[code] || ERROR_CODE_MAP.ERR_INTERNAL_SERVER_ERROR;
  return {
    code,
    titleFa: known.titleFa,
    messageFa: known.messageFa,
    suggestedActionFa: known.suggestedActionFa,
    rawError: str,
    technicalDetails: str,
  };
}
