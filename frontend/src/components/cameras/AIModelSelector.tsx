import { useState, useRef, useEffect } from 'react';
import './AIModelSelector.css';
import { GeofenceSetupModal } from '../GeofenceSetupModal';
import type { ModelConfig } from '../../types/geofencing';

/**
 * AIModelSelector Component
 *
 * Per-camera AI model toggle dropdown.
 * Per F7 §5:
 * - Available models shown with checkboxes
 * - Model states: Active (●), Inactive (○), Degraded (◐), Unavailable (✖)
 * - Changes apply immediately
 * - Session-scoped (not persisted to localStorage)
 *
 * Model states per F7 §5.3:
 * - Active: Model enabled, detection overlay visible
 * - Inactive: Model available but not enabled
 * - Degraded: Model enabled but experiencing issues
 * - Unavailable: Model not accessible (system issue)
 *
 * Geo-fencing Support:
 * - Models that require geo-fencing show a settings button
 * - Clicking the button opens GeofenceSetupModal
 * - Configuration is stored per camera-model pair
 */

export type AIModelState = 'active' | 'inactive' | 'degraded' | 'unavailable';

export interface AIModel {
  id: string;
  name: string;
  state: AIModelState;
  requiresGeofencing?: boolean;
}

interface AIModelSelectorProps {
  cameraId: string;
  cameraName: string;
  videoUrl: string;
  models: AIModel[];
  onModelToggle: (modelId: string, enabled: boolean, config?: ModelConfig) => void;
  modelConfigs?: Record<string, ModelConfig>;
}

export function AIModelSelector({
  cameraId,
  cameraName,
  videoUrl,
  models,
  onModelToggle,
  modelConfigs = {}
}: AIModelSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [geofenceModalOpen, setGeofenceModalOpen] = useState(false);
  const [selectedModelForConfig, setSelectedModelForConfig] = useState<AIModel | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => {
        document.removeEventListener('mousedown', handleClickOutside);
      };
    }
  }, [isOpen]);

  const handleToggle = (model: AIModel, currentState: AIModelState) => {
    // Only allow toggling if not unavailable
    if (currentState === 'unavailable') return;

    const isEnabled = currentState === 'active' || currentState === 'degraded';

    // If enabling a model that requires geo-fencing and no config exists, open modal
    if (!isEnabled && model.requiresGeofencing && !modelConfigs[model.id]) {
      setSelectedModelForConfig(model);
      setGeofenceModalOpen(true);
      return;
    }

    // Otherwise toggle normally
    onModelToggle(model.id, !isEnabled, modelConfigs[model.id]);
  };

  const handleGeofenceSetup = (model: AIModel) => {
    setSelectedModelForConfig(model);
    setGeofenceModalOpen(true);
  };

  const handleConfigSaved = (config: ModelConfig) => {
    if (!selectedModelForConfig) return;

    // Close modal
    setGeofenceModalOpen(false);

    // Enable the model with the new config
    onModelToggle(selectedModelForConfig.id, true, config);

    setSelectedModelForConfig(null);
  };

  const getStateIndicator = (state: AIModelState): string => {
    switch (state) {
      case 'active':
        return '●';
      case 'inactive':
        return '○';
      case 'degraded':
        return '◐';
      case 'unavailable':
        return '✖';
    }
  };

  const getStateLabel = (state: AIModelState): string => {
    switch (state) {
      case 'active':
        return 'Active';
      case 'inactive':
        return 'Inactive';
      case 'degraded':
        return 'Degraded';
      case 'unavailable':
        return 'Unavailable';
    }
  };

  const getStateClass = (state: AIModelState): string => {
    switch (state) {
      case 'active':
        return 'ai-model-selector__state--active';
      case 'inactive':
        return 'ai-model-selector__state--inactive';
      case 'degraded':
        return 'ai-model-selector__state--degraded';
      case 'unavailable':
        return 'ai-model-selector__state--unavailable';
    }
  };

  return (
    <div className="ai-model-selector" ref={dropdownRef}>
      <button
        type="button"
        className="ai-model-selector__trigger"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        aria-haspopup="true"
        aria-label="AI detection models"
      >
        AI Models ▼
      </button>

      {isOpen && (
        <div className="ai-model-selector__panel" role="dialog" aria-label="AI detection models">
          <div className="ai-model-selector__header">
            <h4 className="ai-model-selector__title">AI DETECTION MODELS</h4>
            <button
              type="button"
              className="ai-model-selector__close"
              onClick={() => setIsOpen(false)}
              aria-label="Close"
            >
              ✕
            </button>
          </div>

          <div className="ai-model-selector__content">
            <p className="ai-model-selector__subtitle">Available for this camera:</p>

            <div className="ai-model-selector__list">
              {models.map((model) => {
                const isEnabled = model.state === 'active' || model.state === 'degraded';
                const isDisabled = model.state === 'unavailable';
                const hasConfig = !!modelConfigs[model.id];

                return (
                  <div
                    key={model.id}
                    className={`ai-model-selector__item ${
                      isDisabled ? 'ai-model-selector__item--disabled' : ''
                    }`}
                  >
                    <label className="ai-model-selector__item-content">
                      <input
                        type="checkbox"
                        checked={isEnabled}
                        onChange={() => handleToggle(model, model.state)}
                        disabled={isDisabled}
                        className="ai-model-selector__checkbox"
                      />
                      <span className="ai-model-selector__model-name">{model.name}</span>
                      <span className={`ai-model-selector__state ${getStateClass(model.state)}`}>
                        {getStateIndicator(model.state)} {getStateLabel(model.state)}
                      </span>
                    </label>
                    {model.requiresGeofencing && !isDisabled && (
                      <button
                        type="button"
                        className="ai-model-selector__config-btn"
                        onClick={() => handleGeofenceSetup(model)}
                        aria-label="Setup geo-fence"
                        title={hasConfig ? 'Edit geo-fence configuration' : 'Setup geo-fence configuration'}
                      >
                        ⚙️
                      </button>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="ai-model-selector__note">
              <p>Note: Changes apply immediately.</p>
              <p>Detection overlays show for active models.</p>
            </div>
          </div>
        </div>
      )}

      {/* Geo-fence Setup Modal */}
      {geofenceModalOpen && selectedModelForConfig && (
        <GeofenceSetupModal
          isOpen={geofenceModalOpen}
          onClose={() => {
            setGeofenceModalOpen(false);
            setSelectedModelForConfig(null);
          }}
          cameraId={cameraId}
          cameraName={cameraName}
          modelId={selectedModelForConfig.id}
          modelName={selectedModelForConfig.name}
          videoUrl={videoUrl}
          onConfigSaved={handleConfigSaved}
          initialConfig={modelConfigs[selectedModelForConfig.id]}
        />
      )}
    </div>
  );
}