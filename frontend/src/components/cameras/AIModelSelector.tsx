import { useState, useRef, useEffect } from 'react';
import './AIModelSelector.css';

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
 */

export type AIModelState = 'active' | 'inactive' | 'degraded' | 'unavailable';

export interface AIModel {
  id: string;
  name: string;
  state: AIModelState;
}

interface AIModelSelectorProps {
  cameraId: string;
  models: AIModel[];
  onModelToggle: (modelId: string, enabled: boolean) => void;
}

export function AIModelSelector({ cameraId: _cameraId, models, onModelToggle }: AIModelSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
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

  const handleToggle = (modelId: string, currentState: AIModelState) => {
    // Only allow toggling if not unavailable
    if (currentState === 'unavailable') return;

    const isEnabled = currentState === 'active' || currentState === 'degraded';
    onModelToggle(modelId, !isEnabled);
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

                return (
                  <label
                    key={model.id}
                    className={`ai-model-selector__item ${
                      isDisabled ? 'ai-model-selector__item--disabled' : ''
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isEnabled}
                      onChange={() => handleToggle(model.id, model.state)}
                      disabled={isDisabled}
                      className="ai-model-selector__checkbox"
                    />
                    <span className="ai-model-selector__model-name">{model.name}</span>
                    <span className={`ai-model-selector__state ${getStateClass(model.state)}`}>
                      {getStateIndicator(model.state)} {getStateLabel(model.state)}
                    </span>
                  </label>
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
    </div>
  );
}