// Adapted from SlicerCustomAppTemplate; Copyright (c) Kitware, Inc.
// Apache-2.0; see packaging/TEMPLATE_NOTICE.txt and LICENSE.
#ifndef qMeniscusAnnotatorAppMainWindow_h
#define qMeniscusAnnotatorAppMainWindow_h
#include "qMeniscusAnnotatorAppExport.h"
#include "qSlicerMainWindow.h"
class Q_MENISCUSANNOTATOR_APP_EXPORT qMeniscusAnnotatorAppMainWindow : public qSlicerMainWindow
{
  Q_OBJECT
public:
  explicit qMeniscusAnnotatorAppMainWindow(QWidget* parent = nullptr);
  ~qMeniscusAnnotatorAppMainWindow() override = default;
private:
  Q_DISABLE_COPY(qMeniscusAnnotatorAppMainWindow);
};
#endif
