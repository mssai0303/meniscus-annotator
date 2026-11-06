// Adapted from SlicerCustomAppTemplate; Copyright (c) Kitware, Inc.
// Apache-2.0; see packaging/TEMPLATE_NOTICE.txt and LICENSE.
#include "qMeniscusAnnotatorAppMainWindow.h"
#include <QFont>
#include <QIcon>
qMeniscusAnnotatorAppMainWindow::qMeniscusAnnotatorAppMainWindow(QWidget* parent)
  : qSlicerMainWindow(parent)
{
  setWindowIcon(QIcon(":/MeniscusAnnotator/DesktopIcon.png"));
  setFont(QFont("Segoe UI", 10));
  setMinimumSize(1024, 700);
}
