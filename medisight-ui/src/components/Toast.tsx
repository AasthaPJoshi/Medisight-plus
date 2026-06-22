/**
 * COMPONENT: Toast
 * Global toast notification system.
 * Usage: const { toast } = useToast(); toast('Saved', 'success');
 */

import React, { createContext, useContext, useState, useCallback, ReactNode } from 'react';

type ToastType = 'success' | 'error' | 'info' | 'warn';

interface ToastItem { id: number; msg: string; type: ToastType; }

interface ToastCtx { toast: (msg: string, type?: ToastType) => void; }

const ToastContext = createContext<ToastCtx>({ toast: () => {} });

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const toast = useCallback((msg: string, type: ToastType = 'info') => {
    const id = Date.now() + Math.random();
    setItems(prev => [...prev, { id, msg, type }]);
    setTimeout(() => setItems(prev => prev.filter(t => t.id !== id)), 3600);
  }, []);

  const icons: Record<ToastType, string> = {
    success: '✓', error: '✕', info: 'ℹ', warn: '⚠',
  };

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      {items.length > 0 && (
        <div className="toast-wrap">
          {items.map(t => (
            <div key={t.id} className={`toast toast-${t.type}`}>
              <span>{icons[t.type]}</span>
              <span>{t.msg}</span>
            </div>
          ))}
        </div>
      )}
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
