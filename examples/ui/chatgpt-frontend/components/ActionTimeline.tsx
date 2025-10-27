'use client'

import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

interface Step {
  stepNumber: number
  action: string
  thought?: string
  screenshot?: string
  timestamp: string
}

interface ActionTimelineProps {
  steps: Step[]
}

export default function ActionTimeline({ steps }: ActionTimelineProps) {
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set())

  const toggleStep = (stepNumber: number) => {
    const newExpanded = new Set(expandedSteps)
    if (newExpanded.has(stepNumber)) {
      newExpanded.delete(stepNumber)
    } else {
      newExpanded.add(stepNumber)
    }
    setExpandedSteps(newExpanded)
  }

  if (steps.length === 0) {
    return null
  }

  return (
    <div className="mt-6 border-t border-chatgpt-gray-200 dark:border-chatgpt-gray-700 pt-4">
      <h3 className="text-sm font-semibold mb-3 text-chatgpt-gray-200">
        Timeline de Ações ({steps.length} steps)
      </h3>

      <div className="space-y-2">
        {steps.map((step) => {
          const isExpanded = expandedSteps.has(step.stepNumber)

          return (
            <div
              key={step.stepNumber}
              className="border border-chatgpt-gray-200 dark:border-chatgpt-gray-700 rounded-lg overflow-hidden"
            >
              {/* Step Header */}
              <button
                onClick={() => toggleStep(step.stepNumber)}
                className="w-full flex items-center gap-3 px-4 py-3 hover:bg-chatgpt-gray-50 dark:hover:bg-chatgpt-gray-800 transition-colors"
              >
                {isExpanded ? (
                  <ChevronDown size={16} className="flex-shrink-0" />
                ) : (
                  <ChevronRight size={16} className="flex-shrink-0" />
                )}

                <div className="flex-1 text-left">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-chatgpt-gray-200">
                      Step {step.stepNumber}
                    </span>
                    <span className="text-sm font-medium">{step.action}</span>
                  </div>
                  <div className="text-xs text-chatgpt-gray-200 mt-0.5">
                    {new Date(step.timestamp).toLocaleTimeString('pt-BR')}
                  </div>
                </div>
              </button>

              {/* Step Details (expandible) */}
              {isExpanded && (
                <div className="px-4 pb-4 border-t border-chatgpt-gray-200 dark:border-chatgpt-gray-700">
                  {/* Thought */}
                  {step.thought && (
                    <div className="mt-3">
                      <div className="text-xs font-semibold text-chatgpt-gray-200 mb-1">
                        Pensamento:
                      </div>
                      <div className="text-sm bg-chatgpt-gray-50 dark:bg-chatgpt-gray-900 rounded p-3">
                        {step.thought}
                      </div>
                    </div>
                  )}

                  {/* Screenshot */}
                  {step.screenshot && (
                    <div className="mt-3">
                      <div className="text-xs font-semibold text-chatgpt-gray-200 mb-1">
                        Screenshot:
                      </div>
                      <img
                        src={`data:image/png;base64,${step.screenshot}`}
                        alt={`Step ${step.stepNumber}`}
                        className="rounded border border-chatgpt-gray-200 dark:border-chatgpt-gray-700 max-w-full h-auto cursor-pointer hover:opacity-90"
                        onClick={() => {
                          const win = window.open()
                          if (win) {
                            win.document.write(
                              `<img src="data:image/png;base64,${step.screenshot}" />`
                            )
                          }
                        }}
                      />
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
