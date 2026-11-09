// Adapted from SlicerCustomAppTemplate; Copyright (c) Kitware, Inc.
// Apache-2.0; see packaging/TEMPLATE_NOTICE.txt and LICENSE.
#include "qMeniscusAnnotatorAppMainWindow.h"
#include "qSlicerApplication.h"
#include "qSlicerStyle.h"
#include "qSlicerApplicationHelper.h"
#include "vtkSlicerConfigure.h"
#include "vtkSlicerVersionConfigure.h"
#include <QApplication>
#include <QScopedPointer>
namespace {
int SlicerAppMain(int argc, char* argv[])
{
  QApplication::setAttribute(Qt::AA_EnableHighDpiScaling);
  QApplication::setAttribute(Qt::AA_UseHighDpiPixmaps);
  QGuiApplication::setHighDpiScaleFactorRoundingPolicy(Qt::HighDpiScaleFactorRoundingPolicy::PassThrough);
  qSlicerApplicationHelper::preInitializeApplication(argv[0], new qSlicerStyle);
  qSlicerApplication app(argc, argv);
  if (app.returnCode() != -1) { return app.returnCode(); }
  QScopedPointer<qMeniscusAnnotatorAppMainWindow> window;
  QScopedPointer<QSplashScreen> splashScreen;
  const int exitCode = qSlicerApplicationHelper::postInitializeApplication<qMeniscusAnnotatorAppMainWindow>(app, splashScreen, window);
  if (exitCode != 0) { return exitCode; }
  if (!window.isNull()) {
    window->setWindowTitle(QString("%1 %2").arg(Slicer_MAIN_PROJECT_APPLICATION_DISPLAY_NAME).arg(Slicer_MAIN_PROJECT_VERSION_FULL));
  }
  return app.exec();
}
}
#include "qSlicerApplicationMainWrapper.cxx"
