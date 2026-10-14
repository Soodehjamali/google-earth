import { useNavigate } from 'react-router-dom';
import AgricultureHistorySection from '../components/agriculture/AgricultureHistorySection';

export default function Reports() {
  const navigate = useNavigate();

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">گزارش‌ها و تاریخچه تحلیل‌ها</h2>
        <p className="page-subtitle">Reports & Persistent History — بازیابی و مدیریت گزارش‌های ذخیره‌شده اراضی</p>
      </div>

      <AgricultureHistorySection
        onSelectAnalysis={(analysisId) => {
          navigate(`/agriculture?analysis_id=${analysisId}`);
        }}
      />
    </div>
  );
}

